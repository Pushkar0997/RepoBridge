"""
Content extraction: turn a selected file's text into normalised, traceable chunks.

Two rules shape this module:

- **Every chunk is traceable.** A chunk carries its source path and its position within
  that file; notebook chunks also carry the cell index and cell type. A chunk that cannot
  be traced back to where it came from is the same defect as a file that vanishes.
- **Partial success is not failure.** One file failing to fetch or decode records a
  reason and the run continues. A single bad notebook must not cost you the other 199
  files.

This module performs no HTTP. `fetch_and_extract` takes a `fetch` callable, so the
orchestration is testable without a network or a mock transport.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import posixpath
from dataclasses import dataclass, field
from enum import Enum
from typing import Awaitable, Callable, Sequence

from repobridge.config import DEFAULT_EXTRACTION_CONFIG, ExtractionConfig


class ChunkType(str, Enum):
    """What kind of text a chunk holds. Notebook cells keep their own types."""

    MARKDOWN = "markdown"
    TEXT = "text"
    CODE = "code"
    DATA = "data"
    NOTEBOOK_MARKDOWN = "notebook_markdown"
    NOTEBOOK_CODE = "notebook_code"
    NOTEBOOK_RAW = "notebook_raw"


class ContentStatus(str, Enum):
    """
    Outcome of reading one selected file.

    Extends the classification identity rather than replacing it: a file is classified
    `selected`, and then separately read, failed, or never reached.

        selected == read + failed + not_fetched
    """

    READ = "read"
    FAILED = "failed"
    NOT_FETCHED = "not_fetched"


class ExtractionError(Exception):
    """A file was retrieved but could not be turned into text."""


@dataclass(frozen=True)
class Chunk:
    source_path: str
    chunk_index: int
    chunk_type: ChunkType
    text: str
    #: notebooks only: position of the cell in the notebook, 0-based
    cell_index: int | None = None

    @property
    def char_count(self) -> int:
        return len(self.text)

    def token_estimate(self, cfg: ExtractionConfig = DEFAULT_EXTRACTION_CONFIG) -> int:
        return max(1, len(self.text) // cfg.chars_per_token) if self.text else 0


@dataclass
class FileExtraction:
    path: str
    status: ContentStatus
    chunks: list[Chunk] = field(default_factory=list)
    byte_count: int | None = None
    content_sha: str | None = None
    error: str | None = None


@dataclass
class ExtractionResult:
    selected_total: int = 0
    files: list[FileExtraction] = field(default_factory=list)
    cap: int = 0

    @property
    def read(self) -> list[FileExtraction]:
        return [f for f in self.files if f.status is ContentStatus.READ]

    @property
    def failed(self) -> list[FileExtraction]:
        return [f for f in self.files if f.status is ContentStatus.FAILED]

    @property
    def not_fetched(self) -> list[FileExtraction]:
        return [f for f in self.files if f.status is ContentStatus.NOT_FETCHED]

    @property
    def chunks(self) -> list[Chunk]:
        return [c for f in self.files for c in f.chunks]

    @property
    def cap_applied(self) -> bool:
        return len(self.not_fetched) > 0

    def accounts_for_every_selected_file(self) -> bool:
        """Same promise as classification, one stage later."""
        return self.selected_total == len(self.read) + len(self.failed) + len(self.not_fetched)


# --------------------------------------------------------------------------
# per-format extraction
# --------------------------------------------------------------------------

#: Extensions whose content is prose. Everything readable that is not prose, data or a
#: notebook is treated as code: text with its structure left intact.
_PROSE_EXTENSIONS = {".md", ".markdown", ".rst", ".txt"}
_DATA_EXTENSIONS = {".json", ".yml", ".yaml", ".toml", ".cfg", ".cnf", ".ini", ".in"}


def _chunk_type_for(path: str) -> ChunkType:
    extension = posixpath.splitext(posixpath.basename(path))[1].lower()
    if extension in _PROSE_EXTENSIONS:
        return ChunkType.MARKDOWN if extension in {".md", ".markdown"} else ChunkType.TEXT
    if extension in _DATA_EXTENSIONS:
        return ChunkType.DATA
    return ChunkType.CODE


def _cell_text(source) -> str:
    """Notebook `source` is either a string or a list of lines. Both are legal."""
    if isinstance(source, list):
        return "".join(str(line) for line in source)
    return str(source or "")


def extract_notebook(path: str, content: str) -> list[Chunk]:
    """
    Flatten a notebook to one chunk per cell, preserving cell index and type.

    spec.md section 7.5 requires markdown cells as prose and code cells as code blocks,
    kept distinct. The cell index is preserved so a chunk traces to a position in the
    notebook, not merely to the file.
    """
    try:
        document = json.loads(content)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ExtractionError(f"Notebook is not valid JSON: {exc}") from exc

    if not isinstance(document, dict):
        raise ExtractionError("Notebook JSON is not an object.")

    cells = document.get("cells")
    if cells is None:
        raise ExtractionError("Notebook has no 'cells' key; it may not be a Jupyter notebook.")
    if not isinstance(cells, list):
        raise ExtractionError("Notebook 'cells' is not a list.")

    types = {
        "markdown": ChunkType.NOTEBOOK_MARKDOWN,
        "code": ChunkType.NOTEBOOK_CODE,
        "raw": ChunkType.NOTEBOOK_RAW,
    }

    chunks: list[Chunk] = []
    for cell_index, cell in enumerate(cells):
        if not isinstance(cell, dict):
            # one malformed cell does not discard the notebook
            continue
        text = _cell_text(cell.get("source")).strip("\n")
        if not text.strip():
            continue
        chunk_type = types.get(str(cell.get("cell_type")), ChunkType.NOTEBOOK_RAW)
        chunks.append(
            Chunk(
                source_path=path,
                chunk_index=len(chunks),
                chunk_type=chunk_type,
                text=text,
                cell_index=cell_index,
            )
        )
    return chunks


def extract_file(path: str, content: str) -> list[Chunk]:
    """
    Normalise one file's text into chunks.

    Notebooks become one chunk per cell. Everything else becomes a single chunk: v0.1
    does not split by size, because no token budget exists yet to split against. The
    chunk index is still recorded, so splitting later does not change the model.
    """
    if posixpath.splitext(path)[1].lower() == ".ipynb":
        return extract_notebook(path, content)

    text = content.replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        return []
    return [
        Chunk(
            source_path=path,
            chunk_index=0,
            chunk_type=_chunk_type_for(path),
            text=text,
        )
    ]


def content_sha(content: str) -> str:
    """spec.md section 7.4 asks for a hash alongside the stored content."""
    return hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()


# --------------------------------------------------------------------------
# orchestration
# --------------------------------------------------------------------------

FetchCallable = Callable[[str], Awaitable[str]]


async def fetch_and_extract(
    selected_paths: Sequence[str],
    fetch: FetchCallable,
    cfg: ExtractionConfig = DEFAULT_EXTRACTION_CONFIG,
) -> ExtractionResult:
    """
    Read up to `cfg.max_files_per_run` selected files and extract each into chunks.

    `fetch(path) -> str` supplies content; any exception it raises is recorded against
    that file and the run continues. Files past the cap are recorded as `not_fetched`
    with a reason, never dropped: the caller must be able to say "read 200 of 11,215".

    Reads run concurrently, bounded by `cfg.max_concurrent_reads`. Error isolation is
    per-file and unchanged: `read_one` never raises, so one failure cannot cancel the
    others, and the identity still holds.
    """
    result = ExtractionResult(selected_total=len(selected_paths), cap=cfg.max_files_per_run)

    to_read = list(selected_paths[: cfg.max_files_per_run])
    beyond_cap = list(selected_paths[cfg.max_files_per_run :])

    # Bounded concurrency. Unbounded gather over 200 files would hammer GitHub and is
    # what actually trips secondary rate limits; the semaphore keeps at most
    # `max_concurrent_reads` requests in flight.
    semaphore = asyncio.Semaphore(max(1, cfg.max_concurrent_reads))

    async def read_one(path: str) -> FileExtraction:
        """Read and extract one file. Never raises: one file must not end the run."""
        async with semaphore:
            try:
                content = await fetch(path)
            except Exception as exc:  # noqa: BLE001 - isolation is the point
                return FileExtraction(
                    path=path,
                    status=ContentStatus.FAILED,
                    error=f"Could not read file: {exc}",
                )

        try:
            chunks = extract_file(path, content)
        except ExtractionError as exc:
            return FileExtraction(
                path=path,
                status=ContentStatus.FAILED,
                byte_count=len(content.encode("utf-8", errors="replace")),
                content_sha=content_sha(content),
                error=str(exc),
            )

        return FileExtraction(
            path=path,
            status=ContentStatus.READ,
            chunks=chunks,
            byte_count=len(content.encode("utf-8", errors="replace")),
            content_sha=content_sha(content),
        )

    if to_read:
        # gather preserves input order, so `files` stays in selection order regardless
        # of which requests finish first
        result.files.extend(await asyncio.gather(*(read_one(path) for path in to_read)))

    for path in beyond_cap:
        result.files.append(
            FileExtraction(
                path=path,
                status=ContentStatus.NOT_FETCHED,
                error=(
                    f"Not read: this run reads at most {cfg.max_files_per_run} files and "
                    f"{len(selected_paths)} were selected."
                ),
            )
        )

    return result
