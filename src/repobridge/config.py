from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class GitHubConfig:
    api_base_url: str = "https://api.github.com"
    api_version: str = "2022-11-28"  # GitHub API version header
    token_env_var: str = "REPOBRIDGE_GITHUB_TOKEN"
    metadata_timeout: float = 10.0
    tree_timeout: float = 15.0


# Default config instance. Callers (and tests) can pass their own.
DEFAULT_GITHUB_CONFIG = GitHubConfig()


def get_github_token(cfg: GitHubConfig = DEFAULT_GITHUB_CONFIG) -> str | None:
    """
    Return the GitHub token from environment if set, otherwise None.
    v0.1 keeps this very simple: no secret storage, just an env variable.

    The env var name comes from the supplied config, so injecting a config with a
    different `token_env_var` actually takes effect.
    """
    return os.getenv(cfg.token_env_var)


@dataclass(frozen=True)
class SelectionConfig:
    """
    Thresholds and rule sets for file classification.

    Data lives here so the threshold is configurable rather than hardcoded; the rules
    that consume it live in `core/selection.py`. Frozen, with immutable collections,
    because a shared default instance must not be mutable.

    Supported extensions and filenames come from `specs/001-repobridge-v0.1/selection.md`,
    including its two 2026-08-17 amendments. `.js`/`.ts` are optional there and are included:
    v0.1 extraction treats code as plain text, so they cost nothing extra.
    """

    # A file larger than this is skipped even when its type is supported.
    max_file_bytes: int = 1_000_000

    supported_extensions: frozenset[str] = frozenset(
        {
            # prose and docs
            ".md", ".markdown", ".rst", ".txt",
            # code
            ".py", ".js", ".ts", ".sh",
            # notebooks
            ".ipynb",
            # structured config. `.cnf` is OpenSSL config: same key=value shape as .ini/.cfg
            ".json", ".yml", ".yaml", ".toml", ".cfg", ".cnf", ".ini", ".in",
            # `.bat` is the Windows counterpart of `.sh`; supporting one and not the
            # other was asymmetry rather than judgement (selection.md, 2nd amendment)
            ".bat",
            # template variants of config files: text by construction, and often the
            # only committed form (.env.example, config.yml.template)
            ".example", ".template", ".sample",
        }
    )

    # Files with no usable extension that are still worth reading, matched by exact
    # filename. Dockerfile/Makefile/.gitignore carry real signal about how a project
    # builds and runs. Closed set: anything extensionless not listed here is skipped.
    supported_filenames: frozenset[str] = frozenset(
        {
            "Dockerfile", "Makefile", "Rakefile", "Vagrantfile", "Procfile",
            "Gemfile", "Pipfile", "CODEOWNERS",
            "LICENSE", "LICENCE", "COPYING", "NOTICE", "AUTHORS", "CONTRIBUTORS",
            "README", "CHANGELOG",
            ".gitignore", ".gitattributes", ".gitmodules", ".git-blame-ignore-revs",
            ".dockerignore", ".editorconfig", ".coveragerc", ".flake8", ".pylintrc",
            ".npmrc", ".nvmrc", ".python-version", ".ruby-version", ".tool-versions",
            ".prettierrc", ".eslintrc", ".babelrc", ".browserslistrc",
            # Zero-byte marker files: their existence is the signal, so they belong in
            # the readable inventory even though their content is empty. Matched by
            # exact name, so `.typed` is not broadly supported as an extension.
            "py.typed", ".nojekyll",
        }
    )

    # Known non-text types. spec.md names "large images, archives"; this list covers
    # images, archives, media, fonts, compiled artifacts and databases.
    # `.svg` is here by judgement, not by accident — see selection.md.
    non_text_extensions: frozenset[str] = frozenset(
        {
            ".svg",
            ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".tiff", ".webp", ".svgz",
            ".pdf", ".psd", ".ai",
            ".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar", ".jar", ".war",
            ".mp3", ".mp4", ".wav", ".avi", ".mov", ".mkv", ".flac", ".ogg", ".webm",
            ".ttf", ".otf", ".woff", ".woff2", ".eot",
            ".exe", ".dll", ".so", ".dylib", ".bin", ".o", ".a", ".class", ".pyc", ".pyd",
            ".db", ".sqlite", ".sqlite3", ".parquet", ".pickle", ".pkl", ".npy", ".npz",
        }
    )

    # Directory names excluded wherever they appear in a path. spec.md names
    # "node_modules-style folders"; this covers vendored, generated and tooling dirs.
    excluded_directories: frozenset[str] = frozenset(
        {
            "node_modules", "bower_components", "vendor", "third_party", "vendored",
            ".git", ".hg", ".svn",
            "dist", "build", "out", "target", "site-packages",
            ".venv", "venv", "env", "virtualenv",
            "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox",
            ".idea", ".vscode", ".next", ".nuxt", ".cache",
        }
    )

    # Generated dependency lockfiles. These need their own rule because several are
    # `.json` or `.yaml` and would otherwise be selected as supported text.
    lockfile_names: frozenset[str] = frozenset(
        {
            "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "npm-shrinkwrap.json",
            "poetry.lock", "Pipfile.lock", "pdm.lock", "uv.lock",
            "Cargo.lock", "composer.lock", "Gemfile.lock", "go.sum", "flake.lock",
        }
    )


DEFAULT_SELECTION_CONFIG = SelectionConfig()