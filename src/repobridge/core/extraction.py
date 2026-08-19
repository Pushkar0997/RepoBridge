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
from repobridge.core.ranking import rank_files


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


class FailureKind(str, Enum):
    """
    Why a selected file has no content: it never arrived, or it arrived unreadable.

    Both leave the file `FAILED`, so the identity `selected == read + failed +
    not_fetched` is untouched -- but they are two different stages failing. `spec.md`
    section 7 lists "extraction and parsing outcomes" as its own diagnostic category, and
    a malformed notebook reported as a read failure names the wrong stage and sends a
    reader looking at the network when the network was fine.

    Deliberately **not** a new `ContentStatus` and **not** a stored column. The stored
    `content_status` answers "did this file's content make it into the run", where both
    kinds answer no, and the stored `error` string already carries the prose that
    distinguishes them. A column would be a fourth schema version -- and so a forced
    database delete for anyone holding runs -- to record something the diagnostic event
    can carry itself.
    """

    READ = "read"
    EXTRACT = "extract"


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
    #: set only when `status is FAILED`: which stage failed. See `FailureKind`.
    failure_kind: FailureKind | None = None


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
    def read_failures(self) -> list[FileExtraction]:
        """
        Files that never arrived.

        Defined as "not an extraction failure" rather than "kind is READ" so the two
        lists partition `failed` exactly, whatever a future caller forgets to set.
        """
        return [f for f in self.failed if f.failure_kind is not FailureKind.EXTRACT]

    @property
    def extraction_failures(self) -> list[FileExtraction]:
        """Files that arrived and could not be turned into text."""
        return [f for f in self.failed if f.failure_kind is FailureKind.EXTRACT]

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

    **Which files the cap reads is decided by `rank_files`, not by tree order.** Until
    2026-08-18 this took a prefix of classification order, which is GitHub's tree order,
    which is roughly alphabetical -- so a capped `psf/requests` read 18 `.github/` files
    and neither the README nor a single module of `src/requests/`, and the resulting
    summary described the project as "heavily structured around GitHub infrastructure".
    That is `smoke.md` Run 8, and it is the measurement this ordering exists to answer.

    Ranking is a permutation, so the accounting identity is untouched:
    `selected == read + failed + not_fetched` holds exactly as before, over a different
    partition of the same set. A run under the cap reads everything either way; ranking
    only decides the order in which it does.

    Reads run concurrently, bounded by `cfg.max_concurrent_reads`. Error isolation is
    per-file and unchanged: `read_one` never raises, so one failure cannot cancel the
    others, and the identity still holds.
    """
    result = ExtractionResult(selected_total=len(selected_paths), cap=cfg.max_files_per_run)

    by_rank = rank_files(selected_paths)
    to_read = by_rank[: cfg.max_files_per_run]
    beyond_cap = by_rank[cfg.max_files_per_run :]

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
                    failure_kind=FailureKind.READ,
                )

        try:
            chunks = extract_file(path, content)
        except ExtractionError as exc:
            # The file arrived; it is the parse that failed. Attributed to extraction so
            # the timeline names the stage that actually broke.
            return FileExtraction(
                path=path,
                status=ContentStatus.FAILED,
                byte_count=len(content.encode("utf-8", errors="replace")),
                content_sha=content_sha(content),
                error=str(exc),
                failure_kind=FailureKind.EXTRACT,
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
