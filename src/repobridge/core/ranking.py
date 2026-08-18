"""
How RepoBridge decides which content explains a repository.

One ranking, two consumers, and they must not drift apart:

- **`rank_files`** orders the *selected files* so that a capped run reads a representative
  sample rather than whatever sorts first. Used by `core/extraction.py`.
- **`rank_chunks`** (in `core/summarization.py`) orders the *extracted chunks* so a
  budget-limited prompt carries the most explanatory text. Used when building the prompt.

The shared signals live here so a change to "what explains a repository" applies to both
stages at once. They were defended in the Milestone 6 slice and are unchanged:

1. **README and orienting documents first.** A README answers exactly the question a
   summary answers.
2. **Shallower paths before deeper ones.** Depth correlates with specificity.
3. **Explanatory directories (`docs/`) ahead of peripheral ones (`.github/`, `tests/`).**
4. **Prose before code.** Prose states intent; code states mechanism.
5. **Path as a deterministic tiebreak.**

#### The signal file ranking needs that chunk ranking does not: area spread

`rank_chunks` chooses an order over content *that has already been read*, so every part of
the sampled repository is present in the pool and a pure sort only decides what goes first.
`rank_files` chooses *what is read at all*, and a file the cap never reaches cannot be
recovered by any later stage — it is absent from the summary's evidence entirely.

That difference is not theoretical. Measured on `psf/requests` at a cap of 20
(`smoke.md` Run 8, and re-measured while designing this):

| Ordering | What the cap read |
|---|---|
| Path order (what shipped) | 18 of 20 files under `.github/`; no README, no `src/requests/` |
| Signals 1-5 alone | README, then all of `docs/` — still **zero** files of `src/requests/` |
| Signals 1-5 + area spread | README, `docs/index.rst`, `docs/api.rst`, `src/requests/__init__.py`, … |

A pure sort concentrates on whichever bucket sorts first. For chunks that is harmless; for
files it means a whole area of the repository is never seen. So `rank_files` additionally
**round-robins across top-level areas**, taking the best remaining file from each area in
turn. An area that runs out drops out and the others continue, so a repository of three
root files and five thousand under `src/` still spends almost all of its budget on `src/`.
"""

from __future__ import annotations

import posixpath
from collections import defaultdict
from typing import Iterable, Sequence

#: Filenames that describe a repository to a newcomer, most explanatory first.
ORIENTING_NAMES = (
    "readme",
    "index",
    "overview",
    "introduction",
    "getting-started",
    "getting_started",
    "architecture",
    "design",
    "contributing",
    "changelog",
)

#: Directories whose content explains the project, rather than supporting it.
EXPLANATORY_DIRECTORIES = ("docs", "doc", "documentation", "guides", "examples")

#: Directories that exist for tooling or process, not for explaining the project.
PERIPHERAL_DIRECTORIES = (".github", ".circleci", ".azure", "ci", "scripts", "tests", "test")

#: Extensions whose content is prose. Used only when ranking *files*, where no chunk type
#: exists yet -- the one signal the two rankings must derive differently. `rank_chunks`
#: reads the chunk's actual type, which distinguishes a notebook's markdown cells from its
#: code cells; before a file is read, its extension is all there is.
PROSE_EXTENSIONS = frozenset({".md", ".markdown", ".rst", ".txt"})

#: A notebook is prose-ish for ranking: its markdown cells are usually its explanation.
NOTEBOOK_EXTENSIONS = frozenset({".ipynb"})


def path_rank_key(path: str, *, is_prose: bool) -> tuple:
    """
    The shared ordering key for a path. Lower sorts first.

    `is_prose` is supplied by the caller because the two consumers know it differently:
    from the chunk type after reading, or from the extension before.
    """
    lowered = path.lower()
    segments = lowered.split("/")
    depth = len(segments) - 1
    stem = posixpath.splitext(segments[-1])[0]

    orienting = next(
        (i for i, name in enumerate(ORIENTING_NAMES) if stem.startswith(name)),
        len(ORIENTING_NAMES),
    )
    orienting_rank = orienting if orienting < len(ORIENTING_NAMES) else 99

    directory_rank = 1  # ordinary source
    if any(seg in EXPLANATORY_DIRECTORIES for seg in segments[:-1]):
        directory_rank = 0
    elif any(seg in PERIPHERAL_DIRECTORIES for seg in segments[:-1]):
        directory_rank = 2

    return (
        orienting_rank,
        depth if orienting_rank < 99 else 0,  # among orienting files, prefer shallow
        directory_rank,
        depth,
        0 if is_prose else 1,
        path,
    )


def path_is_prose(path: str) -> bool:
    """Prose-ness inferred from the extension, for ranking a file not yet read."""
    extension = posixpath.splitext(posixpath.basename(path))[1].lower()
    return extension in PROSE_EXTENSIONS or extension in NOTEBOOK_EXTENSIONS


def _area(path: str) -> str:
    """The top-level directory, or "" for a file at the repository root."""
    head, _, tail = path.partition("/")
    return head if tail else ""


def rank_files(paths: Sequence[str] | Iterable[str]) -> list[str]:
    """
    Order selected files so that taking a prefix yields a representative sample.

    **This is a permutation and nothing else.** Every input path appears in the output
    exactly once, including duplicates if the caller supplied any. The accounting identity
    `selected == read + failed + not_fetched` depends on that: ranking changes *which*
    files land beyond the cap, never *how many*.

    Files are ranked by `path_rank_key`, grouped by top-level area, and then taken
    round-robin across areas in order of each area's best file -- so a root `README.md`
    still comes first, and no single directory can consume the whole cap.

    Known and measured limitations, recorded rather than tuned away:

    - **Within an area the order is still the rank key, whose last term is the path.** So
      `src/requests/__init__.py` is read before `src/requests/api.py` because of the
      underscore, not because a package entry point was recognised as one. It happens to be
      a good pick here; that is luck, not design.
    - **Equal round-robin over-weights small peripheral areas.** On `github/docs` at a cap
      of 200, `.github/` receives 36 slots -- the same as `content/`, which holds thousands
      of files. Equal shares are chosen because there is no measurement to justify a
      weighting, and 18% of the budget spent on a repository's real CI configuration is a
      cost, not a distortion.
    - **A repository with one top-level directory degenerates to a pure sort**, because
      there is only one area to alternate between.
    """
    grouped: dict[str, list[str]] = defaultdict(list)
    for path in sorted(paths, key=lambda p: path_rank_key(p, is_prose=path_is_prose(p))):
        grouped[_area(path)].append(path)

    # areas visited in order of their single most explanatory file
    areas = sorted(
        grouped, key=lambda a: path_rank_key(grouped[a][0], is_prose=path_is_prose(grouped[a][0]))
    )

    ordered: list[str] = []
    cursors = {area: 0 for area in areas}
    remaining = sum(len(v) for v in grouped.values())
    while remaining:
        for area in areas:
            index = cursors[area]
            if index < len(grouped[area]):
                ordered.append(grouped[area][index])
                cursors[area] = index + 1
                remaining -= 1
    return ordered
