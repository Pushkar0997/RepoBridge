"""
File classification: decide which tree entries RepoBridge will read.

The product promise is that a user can account for every entry GitHub reported. So:

- Every *file* entry lands in exactly one status: SELECTED, SKIPPED or FAILED.
- Every SKIPPED file carries a closed-enum reason code AND a specific human-readable
  message. The code lets diagnostics say "9 binary, 3 too large"; the message tells a
  person why this particular path was skipped.
- Directories are counted, not classified. See ClassificationResult for why.
- Nothing is dropped. `ClassificationResult.accounts_for_every_entry()` proves it.
"""

from __future__ import annotations

import posixpath
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from typing import Any, Iterable

from repobridge.config import DEFAULT_SELECTION_CONFIG, SelectionConfig


class FileStatus(str, Enum):
    """Terminal status for a file entry. Exactly one applies."""

    SELECTED = "selected"
    SKIPPED = "skipped"
    FAILED = "failed"


class SkipReason(str, Enum):
    """
    Closed set of skip reasons.

    Each code corresponds to a distinct *decision mechanism*, not a synonym: path
    position, entry type, filename, extension, or size. Codes are checked in the order
    listed in `classify_entry`, and that order is deliberate.
    """

    EXCLUDED_DIRECTORY = "excluded_directory"
    SUBMODULE = "submodule"
    LOCKFILE = "lockfile"
    NON_TEXT_ASSET = "non_text_asset"
    UNSUPPORTED_EXTENSION = "unsupported_extension"
    TOO_LARGE = "too_large"


@dataclass(frozen=True)
class ClassifiedFile:
    path: str
    status: FileStatus
    extension: str
    size: int | None = None
    reason: SkipReason | None = None
    message: str | None = None


@dataclass
class ClassificationResult:
    """
    The outcome of classifying one tree.

    `directories` is counted separately rather than being classified as SKIPPED.
    Classification answers "will we read this file's content?", which is not a
    meaningful question about a directory; marking them skipped would inflate the skip
    counts with noise and make "14 skipped" misleading to a human reading diagnostics.
    They are still accounted for, via the identity checked by
    `accounts_for_every_entry()`:

        total_entries == directories + selected + skipped + failed
    """

    total_entries: int = 0
    directories: int = 0
    selected: list[ClassifiedFile] = field(default_factory=list)
    skipped: list[ClassifiedFile] = field(default_factory=list)
    failed: list[ClassifiedFile] = field(default_factory=list)

    @property
    def classified_files(self) -> int:
        return len(self.selected) + len(self.skipped) + len(self.failed)

    def accounts_for_every_entry(self) -> bool:
        """No entry may vanish. This is the core promise, stated as an equation."""
        return self.total_entries == self.directories + self.classified_files

    def counts_by_reason(self) -> dict[str, int]:
        """Skip counts grouped by reason code, for diagnostics summaries."""
        counter = Counter(f.reason.value for f in self.skipped if f.reason is not None)
        return dict(sorted(counter.items()))


def _extension_of(path: str) -> str:
    """Lowercased final extension, or "" when the filename has none."""
    return posixpath.splitext(posixpath.basename(path))[1].lower()


@lru_cache(maxsize=8)
def _lowered(names: frozenset[str]) -> frozenset[str]:
    """
    Case-folded copy of a filename set.

    Filenames are matched case-insensitively for the same reason extensions are:
    `dockerfile` and `Dockerfile` are both legal and mean the same thing. Cached
    because classification runs per entry and large repos have tens of thousands.
    """
    return frozenset(name.lower() for name in names)


def _excluded_directory_in(path: str, cfg: SelectionConfig) -> str | None:
    """Return the first excluded directory segment in the path, if any."""
    # Only directory segments count; the filename itself is not a directory.
    for segment in path.split("/")[:-1]:
        if segment in cfg.excluded_directories:
            return segment
    return None


def classify_entry(
    entry: dict[str, Any], cfg: SelectionConfig = DEFAULT_SELECTION_CONFIG
) -> ClassifiedFile | None:
    """
    Classify a single GitHub tree entry.

    Returns None for directories (GitHub type "tree"), which the caller counts rather
    than classifies.

    Rule order matters and is chosen so the reported reason is the most informative
    true one:

    1. malformed entry            -> FAILED    (cannot classify what has no path)
    2. directory                  -> None      (counted, not classified)
    3. submodule                  -> SUBMODULE (contents live in another repo)
    4. inside an excluded dir     -> EXCLUDED_DIRECTORY
    5. lockfile by name           -> LOCKFILE
    6. known non-text asset       -> NON_TEXT_ASSET
    7. extension AND filename
       both unrecognised          -> UNSUPPORTED_EXTENSION
    8. supported but oversized    -> TOO_LARGE
    9. otherwise                  -> SELECTED

    Position beats type beats size. A `.py` under `node_modules/` is excluded for being
    vendored, not for its extension. Size is checked last so TOO_LARGE means "we would
    have read this, but it is too big" rather than doubling up on files already skipped.
    """
    entry_type = entry.get("type")
    path = entry.get("path")

    # 1. Malformed. FAILED exists so a broken entry is recorded, never dropped.
    if not path or not isinstance(path, str):
        return ClassifiedFile(
            path=str(path) if path else "<unknown>",
            status=FileStatus.FAILED,
            extension="",
            message="Tree entry has no usable path and could not be classified.",
        )
    if entry_type not in {"blob", "tree", "commit"}:
        return ClassifiedFile(
            path=path,
            status=FileStatus.FAILED,
            extension=_extension_of(path),
            message=f"Unrecognised tree entry type {entry_type!r}; could not be classified.",
        )

    # 2. Directory: counted by the caller, not classified.
    if entry_type == "tree":
        return None

    extension = _extension_of(path)
    size = entry.get("size")
    basename = posixpath.basename(path)
    # Filenames are matched case-folded, exactly as extensions are.
    folded_name = basename.lower()

    def skip(reason: SkipReason, message: str) -> ClassifiedFile:
        return ClassifiedFile(
            path=path,
            status=FileStatus.SKIPPED,
            extension=extension,
            size=size,
            reason=reason,
            message=message,
        )

    # 3. Submodule: a pointer to another repository, not content we can read.
    if entry_type == "commit":
        return skip(
            SkipReason.SUBMODULE,
            f"'{path}' is a git submodule; its contents live in another repository.",
        )

    # 4. Position: excluded directory anywhere in the path.
    excluded = _excluded_directory_in(path, cfg)
    if excluded:
        return skip(
            SkipReason.EXCLUDED_DIRECTORY,
            f"'{excluded}/' is excluded by default (vendored, generated or tooling directory).",
        )

    # 5. Generated lockfiles, by exact filename.
    if folded_name in _lowered(cfg.lockfile_names):
        return skip(
            SkipReason.LOCKFILE,
            f"'{basename}' is a generated dependency lockfile, not source content.",
        )

    # 6. Known non-text assets. `.svg` is in this set by judgement (selection.md):
    # XML in form, generated export artifact in practice.
    if extension in cfg.non_text_extensions:
        return skip(
            SkipReason.NON_TEXT_ASSET,
            f"'{extension}' files are not read as text content in v0.1 "
            "(binary or generated asset).",
        )

    # 7. Anything we do not handle. Honest catch-all: unknown, not necessarily junk.
    # A recognised extensionless filename (Dockerfile, .gitignore) is supported by name.
    if (
        extension not in cfg.supported_extensions
        and folded_name not in _lowered(cfg.supported_filenames)
    ):
        if extension:
            detail = f"'{extension}' is not a supported text type in v0.1."
        else:
            # Distinguish "we don't recognise this name" from "extensionless files are
            # unsupported" — the latter is no longer true.
            detail = (
                f"'{basename}' has no file extension and is not one of the configuration "
                "filenames v0.1 recognises."
            )
        return skip(SkipReason.UNSUPPORTED_EXTENSION, detail)

    # 8. Supported, but too big to be worth reading.
    if size is not None and size > cfg.max_file_bytes:
        return skip(
            SkipReason.TOO_LARGE,
            f"{size} bytes exceeds the {cfg.max_file_bytes} byte limit for v0.1.",
        )

    # 9. Readable.
    return ClassifiedFile(
        path=path, status=FileStatus.SELECTED, extension=extension, size=size
    )


def classify_tree(
    entries: Iterable[dict[str, Any]], cfg: SelectionConfig = DEFAULT_SELECTION_CONFIG
) -> ClassificationResult:
    """Classify every entry in a GitHub tree payload."""
    result = ClassificationResult()

    for entry in entries:
        result.total_entries += 1
        classified = classify_entry(entry, cfg)

        if classified is None:
            result.directories += 1
        elif classified.status is FileStatus.SELECTED:
            result.selected.append(classified)
        elif classified.status is FileStatus.SKIPPED:
            result.skipped.append(classified)
        else:
            result.failed.append(classified)

    return result
