"""
Tests for file classification.

Pure unit tests: no HTTP, no fixtures needed. The central promise under test is that
every tree entry lands in exactly one bucket and nothing is silently dropped.
"""

from __future__ import annotations

import pytest

from repobridge.config import DEFAULT_SELECTION_CONFIG, SelectionConfig
from repobridge.core.selection import (
    ClassifiedFile,
    FileStatus,
    SkipReason,
    classify_entry,
    classify_tree,
)

CFG = DEFAULT_SELECTION_CONFIG


def blob(path: str, size: int = 100) -> dict:
    return {"path": path, "type": "blob", "mode": "100644", "sha": "b" * 40, "size": size}


def tree_dir(path: str) -> dict:
    return {"path": path, "type": "tree", "mode": "040000", "sha": "t" * 40}


def submodule(path: str) -> dict:
    return {"path": path, "type": "commit", "mode": "160000", "sha": "c" * 40}


def only(entry: dict) -> ClassifiedFile:
    """classify_entry for a case that must not be a directory."""
    result = classify_entry(entry)
    assert result is not None, "expected a classified file, got a directory"
    return result


# --------------------------------------------------------------------------
# selected
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "README.md",
        "docs/guide.markdown",
        "src/app.py",
        "notebooks/analysis.ipynb",
        "data/config.json",
        "notes.txt",
        "web/index.js",
        "web/types.ts",
    ],
)
def test_supported_extensions_are_selected(path):
    result = only(blob(path))
    assert result.status is FileStatus.SELECTED
    assert result.reason is None
    assert result.message is None


def test_selected_file_records_extension_and_size():
    result = only(blob("src/app.py", size=1234))
    assert result.extension == ".py"
    assert result.size == 1234


def test_extension_matching_is_case_insensitive():
    assert only(blob("READRE.MD")).status is FileStatus.SELECTED
    assert only(blob("IMAGE.PNG")).reason is SkipReason.NON_TEXT_ASSET


# --------------------------------------------------------------------------
# each skip reason fires on a representative path
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "entry, expected",
    [
        (blob("node_modules/left-pad/index.js"), SkipReason.EXCLUDED_DIRECTORY),
        (blob("vendor/lib/thing.py"), SkipReason.EXCLUDED_DIRECTORY),
        (blob(".git/config"), SkipReason.EXCLUDED_DIRECTORY),
        (blob("__pycache__/mod.cpython-313.pyc"), SkipReason.EXCLUDED_DIRECTORY),
        (submodule("external/dep"), SkipReason.SUBMODULE),
        (blob("package-lock.json"), SkipReason.LOCKFILE),
        (blob("poetry.lock"), SkipReason.LOCKFILE),
        (blob("go.sum"), SkipReason.LOCKFILE),
        (blob("assets/logo.png"), SkipReason.NON_TEXT_ASSET),
        (blob("dumps/archive.tar"), SkipReason.NON_TEXT_ASSET),
        (blob("fonts/body.woff2"), SkipReason.NON_TEXT_ASSET),
        (blob("main.go"), SkipReason.UNSUPPORTED_EXTENSION),
        # NB: "Makefile" was here until the 2026-08-17 spec amendment made it supported
        (blob("bin/mystery"), SkipReason.UNSUPPORTED_EXTENSION),
        (blob("styles.css"), SkipReason.UNSUPPORTED_EXTENSION),
        (blob("huge.py", size=CFG.max_file_bytes + 1), SkipReason.TOO_LARGE),
    ],
)
def test_each_skip_reason_fires(entry, expected):
    result = only(entry)
    assert result.status is FileStatus.SKIPPED
    assert result.reason is expected


def test_every_skip_reason_in_the_enum_is_reachable():
    """A reason nobody can trigger is a lie in the schema."""
    entries = [
        blob("node_modules/x/index.js"),
        submodule("ext/dep"),
        blob("yarn.lock"),
        blob("a.png"),
        blob("a.go"),
        blob("big.py", size=CFG.max_file_bytes + 1),
    ]
    fired = {only(e).reason for e in entries}
    assert fired == set(SkipReason)


def test_skipped_files_always_carry_a_code_and_a_message():
    entries = [
        blob("node_modules/x/index.js"),
        submodule("ext/dep"),
        blob("yarn.lock"),
        blob("a.png"),
        blob("a.go"),
        blob("nameless"),
        blob("big.py", size=CFG.max_file_bytes + 1),
    ]
    for entry in entries:
        result = only(entry)
        assert result.status is FileStatus.SKIPPED
        assert result.reason is not None, result.path
        assert result.message, result.path
        # the message must name the thing, not just restate the code
        assert result.message != result.reason.value


def test_skip_message_names_the_offending_directory():
    result = only(blob("node_modules/left-pad/index.js"))
    assert "node_modules/" in result.message


# --------------------------------------------------------------------------
# widened supported list (spec.md 7.3 amendment, 2026-08-17)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        ".github/FUNDING.yml",
        "ci/config.yaml",
        "pyproject.toml",
        "setup.cfg",
        "tox.ini",
        "docs/index.rst",
        "requirements.in",
        "scripts/build.sh",
    ],
)
def test_widened_extensions_are_selected(path):
    """These returned unsupported_extension on psf/requests before the amendment."""
    assert only(blob(path)).status is FileStatus.SELECTED


@pytest.mark.parametrize(
    "path", [".env.example", "config.yml.template", "settings.ini.sample"]
)
def test_template_variants_are_selected(path):
    assert only(blob(path)).status is FileStatus.SELECTED


@pytest.mark.parametrize("path", ["tests/certs/ca.cnf", "docs/make.bat"])
def test_second_amendment_extensions_are_selected(path):
    """
    .cnf is key=value config like .ini/.cfg; .bat is the Windows counterpart of .sh.
    Both were in the psf/requests residue, excluded by omission rather than decision.
    """
    assert only(blob(path)).status is FileStatus.SELECTED


def test_bat_and_sh_are_treated_symmetrically():
    """Supporting one build script format and not the other was the actual defect."""
    assert only(blob("scripts/build.sh")).status is FileStatus.SELECTED
    assert only(blob("scripts/build.bat")).status is FileStatus.SELECTED


@pytest.mark.parametrize("path", ["src/pkg/py.typed", "docs/.nojekyll"])
def test_zero_byte_marker_files_are_selected(path):
    """Their existence is the signal, so they belong in the readable inventory."""
    result = only(blob(path, size=0))
    assert result.status is FileStatus.SELECTED


def test_marker_support_is_by_filename_not_by_extension():
    """py.typed is supported; `.typed` is not a broadly supported extension."""
    assert only(blob("pkg/py.typed", size=0)).status is FileStatus.SELECTED
    other = only(blob("pkg/something.typed"))
    assert other.status is FileStatus.SKIPPED
    assert other.reason is SkipReason.UNSUPPORTED_EXTENSION


@pytest.mark.parametrize(
    "path",
    [
        "Dockerfile",
        "Makefile",
        "LICENSE",
        "docker/Dockerfile",
        ".gitignore",
        ".coveragerc",
        ".editorconfig",
        ".github/CODEOWNERS",
        ".git-blame-ignore-revs",
        ".python-version",
    ],
)
def test_recognised_extensionless_files_are_selected(path):
    result = only(blob(path))
    assert result.status is FileStatus.SELECTED
    assert result.extension == ""


def test_unrecognised_extensionless_file_is_skipped_with_an_honest_message():
    """
    Once config filenames are supported, "files without an extension are unsupported"
    would be a false statement. The message must name the file instead.
    """
    result = only(blob("bin/mystery"))
    assert result.status is FileStatus.SKIPPED
    assert result.reason is SkipReason.UNSUPPORTED_EXTENSION
    assert "mystery" in result.message
    assert "not one of the configuration filenames" in result.message
    # the old, now-false blanket claim must be gone
    assert "Files without an extension are not" not in result.message


@pytest.mark.parametrize(
    "path",
    ["Dockerfile", "dockerfile", "DOCKERFILE", "docker/dockerfile", "makefile", "license"],
)
def test_recognised_filenames_match_case_insensitively(path):
    """`dockerfile` and `Dockerfile` are both legal and mean the same thing."""
    assert only(blob(path)).status is FileStatus.SELECTED


@pytest.mark.parametrize("path", ["Cargo.lock", "cargo.lock", "YARN.LOCK"])
def test_lockfile_names_match_case_insensitively(path):
    """Lockfile matching is the same mechanism, so it folds case the same way."""
    assert only(blob(path)).reason is SkipReason.LOCKFILE


def test_case_folding_does_not_select_unrecognised_names():
    """Folding must widen case, not widen the set."""
    assert only(blob("dockerfile.bak")).status is FileStatus.SKIPPED
    assert only(blob("MYSTERY")).status is FileStatus.SKIPPED


def test_recognised_filename_message_contrast():
    """A recognised name is selected; an unrecognised one is skipped and says which."""
    assert only(blob("Makefile")).status is FileStatus.SELECTED
    skipped = only(blob("Makefile.old"))
    assert skipped.status is FileStatus.SKIPPED
    assert "'.old'" in skipped.message


# --------------------------------------------------------------------------
# .svg: decided, not defaulted (spec.md 7.3)
# --------------------------------------------------------------------------


def test_svg_is_skipped_as_a_non_text_asset():
    result = only(blob("assets/logo.svg"))
    assert result.status is FileStatus.SKIPPED
    assert result.reason is SkipReason.NON_TEXT_ASSET
    # the code name must not claim SVG is binary; it is text we choose not to read
    assert result.reason.value == "non_text_asset"


def test_binary_message_does_not_claim_svg_is_binary():
    """SVG is XML text. The message must not assert something false about it."""
    message = only(blob("logo.svg")).message
    assert "generated asset" in message
    assert "cannot be read as text" not in message


# --------------------------------------------------------------------------
# compound extensions
# --------------------------------------------------------------------------


def test_declaration_files_are_selected_via_final_extension():
    """types.d.ts -> '.ts'. Previously unpinned."""
    result = only(blob("types/index.d.ts"))
    assert result.extension == ".ts"
    assert result.status is FileStatus.SELECTED


def test_double_extension_archives_are_binary_via_final_extension():
    result = only(blob("dumps/archive.tar.gz"))
    assert result.extension == ".gz"
    assert result.reason is SkipReason.NON_TEXT_ASSET


# --------------------------------------------------------------------------
# deliberate non-support (spec.md 7.3 "Deliberately not supported")
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path", ["main.go", "src/lib.rs", "App.java", "data/rows.csv", "page.html", "style.css"]
)
def test_deliberately_unsupported_types_are_still_skipped(path):
    """Widening the list must not have quietly pulled these in."""
    assert only(blob(path)).reason is SkipReason.UNSUPPORTED_EXTENSION


def test_widening_did_not_weaken_the_skip_rules():
    """Lockfiles, vendored dirs and size limits are unaffected by the amendment."""
    assert only(blob("package-lock.json")).reason is SkipReason.LOCKFILE
    assert only(blob("node_modules/pkg/config.yml")).reason is SkipReason.EXCLUDED_DIRECTORY
    assert only(blob("big.toml", size=CFG.max_file_bytes + 1)).reason is SkipReason.TOO_LARGE


def test_unknown_extension_is_skipped_with_a_reason_never_dropped():
    result = only(blob("weird/thing.qqq"))
    assert result.status is FileStatus.SKIPPED
    assert result.reason is SkipReason.UNSUPPORTED_EXTENSION
    assert ".qqq" in result.message


def test_file_without_extension_is_skipped_with_a_readable_message():
    # "LICENSE" was used here until the 2026-08-17 amendment made it a recognised name.
    result = only(blob("scripts/runme"))
    assert result.reason is SkipReason.UNSUPPORTED_EXTENSION
    assert "runme" in result.message
    assert "no file extension" in result.message


# --------------------------------------------------------------------------
# size threshold boundary
# --------------------------------------------------------------------------


def test_file_exactly_at_the_threshold_is_selected():
    result = only(blob("big.py", size=CFG.max_file_bytes))
    assert result.status is FileStatus.SELECTED


def test_file_one_byte_over_the_threshold_is_skipped():
    result = only(blob("big.py", size=CFG.max_file_bytes + 1))
    assert result.status is FileStatus.SKIPPED
    assert result.reason is SkipReason.TOO_LARGE
    assert str(CFG.max_file_bytes) in result.message


def test_threshold_comes_from_config_not_hardcoded():
    tiny = SelectionConfig(max_file_bytes=10)
    assert classify_entry(blob("a.py", size=10), tiny).status is FileStatus.SELECTED
    assert classify_entry(blob("a.py", size=11), tiny).reason is SkipReason.TOO_LARGE
    # and the default config disagrees, proving the value was actually injected
    assert classify_entry(blob("a.py", size=11), CFG).status is FileStatus.SELECTED


def test_missing_size_does_not_trigger_too_large():
    entry = {"path": "a.py", "type": "blob", "mode": "100644"}
    assert only(entry).status is FileStatus.SELECTED


# --------------------------------------------------------------------------
# rule precedence
# --------------------------------------------------------------------------


def test_position_beats_extension():
    """A supported file inside an excluded directory is excluded, not selected."""
    result = only(blob("node_modules/pkg/readme.md"))
    assert result.reason is SkipReason.EXCLUDED_DIRECTORY


def test_position_beats_size():
    result = only(blob("node_modules/pkg/big.py", size=CFG.max_file_bytes + 1))
    assert result.reason is SkipReason.EXCLUDED_DIRECTORY


def test_lockfile_beats_supported_extension():
    """package-lock.json is valid .json; without the lockfile rule it would be selected."""
    result = only(blob("package-lock.json"))
    assert result.reason is SkipReason.LOCKFILE


def test_binary_beats_unsupported():
    result = only(blob("a.png"))
    assert result.reason is SkipReason.NON_TEXT_ASSET


def test_size_is_checked_last_so_too_large_means_would_have_read_it():
    """An oversized binary reports NON_TEXT_ASSET: the more informative truth."""
    result = only(blob("huge.png", size=CFG.max_file_bytes + 1))
    assert result.reason is SkipReason.NON_TEXT_ASSET


def test_excluded_directory_matches_at_any_depth():
    assert only(blob("a/b/node_modules/c/d.js")).reason is SkipReason.EXCLUDED_DIRECTORY


def test_file_named_like_an_excluded_directory_is_not_excluded_for_that_reason():
    """Only directory segments count; the filename itself is not a directory."""
    result = only(blob("docs/node_modules"))
    assert result.reason is SkipReason.UNSUPPORTED_EXTENSION


# --------------------------------------------------------------------------
# directories and malformed entries
# --------------------------------------------------------------------------


def test_directories_are_not_classified():
    assert classify_entry(tree_dir("src")) is None


def test_directories_are_counted_not_skipped():
    result = classify_tree([tree_dir("src"), tree_dir("docs"), blob("a.py")])
    assert result.directories == 2
    assert len(result.skipped) == 0
    assert len(result.selected) == 1


def test_entry_without_a_path_is_failed_not_dropped():
    result = classify_entry({"type": "blob", "mode": "100644"})
    assert result is not None
    assert result.status is FileStatus.FAILED
    assert result.message


def test_unrecognised_entry_type_is_failed_not_dropped():
    result = classify_entry({"path": "odd", "type": "sculpture"})
    assert result is not None
    assert result.status is FileStatus.FAILED
    assert "sculpture" in result.message


# --------------------------------------------------------------------------
# the core promise: nothing vanishes
# --------------------------------------------------------------------------


MIXED_TREE = [
    tree_dir("src"),
    tree_dir("node_modules"),
    blob("README.md", 400),
    blob("src/app.py", 900),
    blob("src/util.ts", 300),
    blob("notebooks/run.ipynb", 5000),
    blob("data/config.json", 120),
    blob("notes.txt", 80),
    blob("assets/logo.png", 40_000),
    blob("assets/hero.jpg", 90_000),
    blob("dist/bundle.zip", 100_000),
    blob("package-lock.json", 250_000),
    blob("poetry.lock", 30_000),
    blob("node_modules/left-pad/index.js", 200),
    blob("main.go", 500),
    blob("Makefile", 300),
    blob("huge.py", CFG.max_file_bytes + 1),
    submodule("external/dep"),
    {"type": "blob", "mode": "100644"},  # malformed
]


def test_every_entry_lands_in_exactly_one_status():
    result = classify_tree(MIXED_TREE)

    assert result.total_entries == len(MIXED_TREE)
    assert result.accounts_for_every_entry()

    # exactly one: no path appears in two buckets
    paths = (
        [f.path for f in result.selected]
        + [f.path for f in result.skipped]
        + [f.path for f in result.failed]
    )
    assert len(paths) == len(set(paths))
    assert len(paths) == result.total_entries - result.directories


def test_counts_sum_to_the_total_entry_count():
    result = classify_tree(MIXED_TREE)
    total = (
        result.directories
        + len(result.selected)
        + len(result.skipped)
        + len(result.failed)
    )
    assert total == result.total_entries == len(MIXED_TREE)


def test_counts_by_reason_sums_to_skipped_count():
    result = classify_tree(MIXED_TREE)
    assert sum(result.counts_by_reason().values()) == len(result.skipped)


def test_mixed_tree_classifies_as_expected():
    result = classify_tree(MIXED_TREE)

    selected = {f.path for f in result.selected}
    assert selected == {
        "README.md",
        "src/app.py",
        "src/util.ts",
        "notebooks/run.ipynb",
        "data/config.json",
        "notes.txt",
        # recognised extensionless config, supported since the 2026-08-17 amendment
        "Makefile",
    }
    assert result.directories == 2
    assert len(result.failed) == 1

    by_reason = result.counts_by_reason()
    assert by_reason == {
        "non_text_asset": 2,  # logo.png, hero.jpg
        # dist/bundle.zip is EXCLUDED_DIRECTORY, not NON_TEXT_ASSET: it sits under
        # dist/, and position beats extension. Pinned deliberately.
        "excluded_directory": 2,  # dist/bundle.zip, node_modules/left-pad/index.js
        "lockfile": 2,  # package-lock.json, poetry.lock
        "submodule": 1,
        "too_large": 1,  # huge.py
        "unsupported_extension": 1,  # main.go (Makefile is now supported by name)
    }


def test_empty_tree_is_valid_and_accounts_for_nothing():
    result = classify_tree([])
    assert result.total_entries == 0
    assert result.accounts_for_every_entry()
    assert result.counts_by_reason() == {}
