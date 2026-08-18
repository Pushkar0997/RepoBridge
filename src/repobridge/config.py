from __future__ import annotations

import os
from dataclasses import dataclass, replace


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


@dataclass(frozen=True)
class DatabaseConfig:
    """
    Local SQLite storage. Path comes from config, not hardcoded (AGENTS.md).

    Override with REPOBRIDGE_DATABASE_URL, e.g. to point a scratch run at a temp file.
    Must be an async driver URL: v0.1 uses sqlite+aiosqlite.
    """

    url_env_var: str = "REPOBRIDGE_DATABASE_URL"
    default_url: str = "sqlite+aiosqlite:///./repobridge.db"
    # Rows per executemany batch when persisting classified entries. Large repos are
    # tens of thousands of rows; one statement per row is needlessly slow, and one
    # statement for all of them is needlessly large.
    insert_batch_size: int = 1_000


DEFAULT_DATABASE_CONFIG = DatabaseConfig()


def get_database_url(cfg: DatabaseConfig = DEFAULT_DATABASE_CONFIG) -> str:
    """Database URL from the environment if set, else the configured default."""
    return os.getenv(cfg.url_env_var) or cfg.default_url


@dataclass(frozen=True)
class ExtractionConfig:
    """
    Limits and rules for reading and normalising file content.

    The cap is the important one. `github/docs` selects 11,215 files; at one contents-API
    call each that exceeds the whole authenticated hourly quota for a single repository.
    See the 2026-08-18 amendment in spec.md section 7.4.
    """

    #: Selected files read per run. Beyond this, files are recorded as `not_fetched`
    #: rather than dropped, and the run says how many it read of how many it selected.
    max_files_per_run: int = 200

    #: Env override for the cap, so it is tunable without editing code -- the same
    #: pattern as the token and the database URL.
    max_files_env_var: str = "REPOBRIDGE_MAX_FILES_PER_RUN"

    #: How many file reads run at once. Sequential reads cost ~1s each in round-trip
    #: latency, so 107 files took 100s. Bounded rather than unbounded because
    #: concurrency is what actually trips GitHub's *secondary* rate limits -- the
    #: client detects those (403 + Retry-After), but the cheaper fix is not to
    #: provoke them. 8 is conservative against GitHub's published guidance.
    max_concurrent_reads: int = 8

    #: Per-file content request timeout, seconds.
    content_timeout: float = 15.0

    #: Characters per token, for the stored estimate. A heuristic, not a tokenizer:
    #: no tokenizer dependency is worth adding for a number used only for budgeting.
    chars_per_token: int = 4


DEFAULT_EXTRACTION_CONFIG = ExtractionConfig()


def get_extraction_config(cfg: ExtractionConfig = DEFAULT_EXTRACTION_CONFIG) -> ExtractionConfig:
    """
    Extraction config with the read cap taken from the environment when set.

    Read at call time, not import time: a default argument binds once, which would make
    the cap untunable without a restart and untestable without reaching into module
    internals.
    """
    raw = os.getenv(cfg.max_files_env_var)
    if raw:
        try:
            value = int(raw)
        except ValueError:
            return cfg
        if value > 0:
            return replace(cfg, max_files_per_run=value)
    return cfg


@dataclass(frozen=True)
class SummarizationConfig:
    """
    Grounded summary generation via Google Gemini (AI Studio).

    One provider, no adapter layer. See the 2026-08-18 amendment in spec.md section 7.6
    for why Gemini over Groq, and for the recorded trade-off about free-tier training on
    submitted prompts.
    """

    #: The key is read from the environment only -- never a request field, never stored.
    api_key_env_var: str = "REPOBRIDGE_GEMINI_API_KEY"

    #: Verified working 2026-08-18. `gemini-2.5-flash` is still listed by the models
    #: endpoint but 404s when called, so model IDs must be exercised, not assumed.
    model: str = "gemini-3.7-flash"
    api_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    timeout: float = 120.0

    #: Token budget for the chunk text placed in the prompt. Far below the model's
    #: 1,048,576-token context: the constraint is cost and latency, not capacity.
    #: Measured with the chars//4 heuristic, which is crude -- see the note in
    #: `core/summarization.py`.
    max_prompt_tokens: int = 120_000
    budget_env_var: str = "REPOBRIDGE_SUMMARY_TOKEN_BUDGET"

    #: Cap on generated length.
    max_output_tokens: int = 4096


DEFAULT_SUMMARIZATION_CONFIG = SummarizationConfig()


def get_gemini_api_key(cfg: SummarizationConfig = DEFAULT_SUMMARIZATION_CONFIG) -> str | None:
    """Gemini key from the environment, or None. Never logged, never persisted."""
    return os.getenv(cfg.api_key_env_var)


def get_summarization_config(
    cfg: SummarizationConfig = DEFAULT_SUMMARIZATION_CONFIG,
) -> SummarizationConfig:
    """Config with the token budget taken from the environment when set."""
    raw = os.getenv(cfg.budget_env_var)
    if raw:
        try:
            value = int(raw)
        except ValueError:
            return cfg
        if value > 0:
            return replace(cfg, max_prompt_tokens=value)
    return cfg
