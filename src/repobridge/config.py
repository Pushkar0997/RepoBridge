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

    # No explicit override: a shared instance uses the lower cap, because the read cap is
    # the dominant term in that instance's GitHub budget. See DeploymentConfig.
    deployment = get_deployment_config()
    if deployment.is_shared:
        return replace(cfg, max_files_per_run=deployment.shared_read_cap)
    return cfg


@dataclass(frozen=True)
class DeploymentConfig:
    """
    Running one shared instance for a feedback round, on someone else's keys.

    **This is an interim posture, recorded as such in `plan.md`.** One instance, the
    operator's GitHub token and Gemini key, one database everyone can see. Not multi-user:
    there is no auth, no per-visitor keys and no session isolation, and adding them now
    would be building the wrong milestone.

    What that posture forces is **spend control**, because every visitor is spending the
    operator's quota. Three limits, all off by default so local development is unchanged,
    and all switched on together by `REPOBRIDGE_DEPLOYMENT=shared`:

    - `max_analyses_per_hour` -- the whole instance. The backstop on total spend.
    - `max_analyses_per_hour_per_client` -- one visitor. Stops one person consuming the
      instance's allowance before anyone else arrives.
    - `max_repo_entries` -- how large a repository this instance will accept at all. The
      per-run read cap already bounds content calls; this bounds them *before* the run
      starts, so a 37,393-entry repository costs two GitHub calls and a clear refusal
      rather than the full read budget.

    Every value is an environment variable, because the operator tuning a live demo
    should not be editing code.
    """

    mode_env_var: str = "REPOBRIDGE_DEPLOYMENT"
    #: "local" (default) or "shared". Only affects defaults and what the UI says; every
    #: limit remains individually overridable in either mode.
    mode: str = "local"

    max_analyses_per_hour: int = 0            # 0 == no limit
    max_analyses_per_hour_per_client: int = 0
    max_repo_entries: int = 0

    instance_limit_env_var: str = "REPOBRIDGE_MAX_ANALYSES_PER_HOUR"
    client_limit_env_var: str = "REPOBRIDGE_MAX_ANALYSES_PER_HOUR_PER_CLIENT"
    repo_entries_env_var: str = "REPOBRIDGE_MAX_REPO_ENTRIES"

    #: Applied when mode is "shared" and the specific variable is unset:
    #: (analyses/hour instance-wide, analyses/hour per visitor, max tree entries).
    #:
    #: **These four numbers are one budget, not four preferences.** The arithmetic, with
    #: `shared_read_cap` below, is worked through in the README under "The limits, and the
    #: arithmetic behind them" and asserted by `test_the_shared_defaults_fit_both_quotas`.
    #: In short:
    #:
    #: - **20 analyses/hour instance-wide** is set by the *Gemini* quota, not the GitHub
    #:   one: summarisation is one request per analysis and the free tier is ~500/day, so
    #:   20/hour sustained for a full day is 480 -- inside it by construction. An hourly
    #:   limit cannot otherwise bound a daily quota, and 40/hour would exhaust the day's
    #:   allowance in 12 hours.
    #: - **5/hour per visitor** means one person can take at most a quarter of the
    #:   instance's hour, so a fourth tester arriving still finds it working.
    #: - **5,000 entries** admits every repository in the smoke suite except
    #:   `twitter/twemoji`, `github/docs` and `kubernetes/kubernetes`, and comfortably
    #:   admits `psf/requests` (153), which the landing page suggests as the example.
    shared_defaults: tuple[int, int, int] = (20, 5, 5_000)

    #: Files read per analysis on a shared instance, replacing `ExtractionConfig`'s local
    #: default of 200. Halving it halves the dominant GitHub cost: the worst-case hour
    #: goes from 20x202 = 4,040 calls (81% of the quota, no headroom for the operator's
    #: own use) to 20x102 = 2,040 (41%).
    #:
    #: Quality survives it. `smoke.md` Run 9 scored a `psf/requests` summary at 4.6/5
    #: from **20** files; 100 is five times that, and every run still reports how many of
    #: how many it read.
    shared_read_cap: int = 100

    #: Where the platform tells us to listen. `PORT` unprefixed is the near-universal
    #: convention (Heroku, Render, Fly, Cloud Run, Railway); the prefixed names are
    #: checked first so this project's own variable wins if someone sets both.
    host_env_vars: tuple[str, ...] = ("REPOBRIDGE_HOST", "HOST")
    port_env_vars: tuple[str, ...] = ("REPOBRIDGE_PORT", "PORT")
    default_host: str = "127.0.0.1"
    default_port: int = 8000

    #: Whether stored runs survive a restart. Set to "ephemeral" when the platform wipes
    #: the filesystem, so the UI can stop promising that a run can be come back to.
    storage_env_var: str = "REPOBRIDGE_STORAGE"
    storage: str = "persistent"

    @property
    def is_shared(self) -> bool:
        return self.mode == "shared"

    @property
    def is_ephemeral(self) -> bool:
        return self.storage == "ephemeral"


DEFAULT_DEPLOYMENT_CONFIG = DeploymentConfig()


def _positive_int(name: str) -> int | None:
    """An environment integer, or None when unset or unusable. Never raises."""
    raw = os.getenv(name)
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value >= 0 else None


def get_deployment_config(
    cfg: DeploymentConfig = DEFAULT_DEPLOYMENT_CONFIG,
) -> DeploymentConfig:
    """
    Deployment config from the environment, read at call time.

    Same rule as every other accessor here: reading at call time is what makes a limit
    tunable on a live process and testable without reaching into module internals.
    """
    mode = (os.getenv(cfg.mode_env_var) or cfg.mode).strip().lower()
    if mode not in {"local", "shared"}:
        mode = cfg.mode

    instance, client, entries = (
        cfg.shared_defaults if mode == "shared"
        else (cfg.max_analyses_per_hour, cfg.max_analyses_per_hour_per_client, cfg.max_repo_entries)
    )
    storage = (os.getenv(cfg.storage_env_var) or cfg.storage).strip().lower()
    if storage not in {"persistent", "ephemeral"}:
        storage = cfg.storage

    def override(name: str, fallback: int) -> int:
        """An explicit variable wins, including an explicit 0 meaning "no limit"."""
        value = _positive_int(name)
        return fallback if value is None else value

    return replace(
        cfg,
        mode=mode,
        storage=storage,
        max_analyses_per_hour=override(cfg.instance_limit_env_var, instance),
        max_analyses_per_hour_per_client=override(cfg.client_limit_env_var, client),
        max_repo_entries=override(cfg.repo_entries_env_var, entries),
    )


def get_bind_address(cfg: DeploymentConfig = DEFAULT_DEPLOYMENT_CONFIG) -> tuple[str, int]:
    """
    Where to listen, from the environment.

    A platform that assigns a port expects the process to read it; hardcoding 8000 is the
    single most common reason a container starts and never receives traffic.
    """
    host = next((os.getenv(name) for name in cfg.host_env_vars if os.getenv(name)), None)
    port = next((_positive_int(name) for name in cfg.port_env_vars if _positive_int(name)), None)
    return host or cfg.default_host, port or cfg.default_port


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

    #: Default model. `gemini-3.7-flash` was the original choice and works, but the
    #: free tier gives quality-tier Flash models **20 requests per day**, which is not
    #: enough to develop against: a handful of checks exhausts the model for the day.
    #: The lite tier on this account allows 500/day at the same 250K tokens/minute, so
    #: it is 25x the daily budget for the same throughput. Requests per day is the
    #: binding constraint on this project -- see the 2026-08-18 amendment in
    #: spec.md section 7.6.
    #:
    #: Model IDs must be *exercised*, not read off the listing endpoint:
    #: `gemini-2.5-flash` is still listed and 404s when called.
    model: str = "gemini-3.5-flash-lite"

    #: Env override for the model, read at call time by `get_summarization_config()`.
    #: The quota is per model, so switching models is the one recovery available when
    #: a day's allowance is gone -- it must not need a code edit.
    model_env_var: str = "REPOBRIDGE_GEMINI_MODEL"

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

    # --- retry policy -----------------------------------------------------
    # `503 "This model is currently experiencing high demand"` is common on the free
    # tier and is not correlated with request size: identical calls alternate between
    # 200 and 503. A single 503 should not cost a run its summary when the daily
    # request allowance is the scarce resource.

    #: Total attempts including the first. 3 means at most two retries.
    max_attempts: int = 3

    #: First backoff delay, seconds. Doubles per attempt, capped by `retry_max_delay`.
    retry_initial_delay: float = 1.0

    #: Ceiling on any single wait, seconds.
    retry_max_delay: float = 16.0

    #: Ceiling on the *total* time spent waiting across all retries, seconds. A wait
    #: that cannot fit inside what is left of this budget is not attempted at all:
    #: sleeping against a wall we cannot clear just delays the same failure.
    retry_budget_seconds: float = 45.0


DEFAULT_SUMMARIZATION_CONFIG = SummarizationConfig()


def get_gemini_api_key(cfg: SummarizationConfig = DEFAULT_SUMMARIZATION_CONFIG) -> str | None:
    """Gemini key from the environment, or None. Never logged, never persisted."""
    return os.getenv(cfg.api_key_env_var)


def get_summarization_config(
    cfg: SummarizationConfig = DEFAULT_SUMMARIZATION_CONFIG,
) -> SummarizationConfig:
    """
    Config with the token budget and the model taken from the environment when set.

    Both are read **at call time**, not bound at import or in a default argument. The
    same mistake froze the extraction cap once already (see `get_extraction_config`):
    a value bound at definition time cannot be changed without a restart and cannot be
    tested without reaching into module internals. The model matters more than the cap
    did -- the daily quota is per model, so switching models is the only recovery from
    an exhausted day, and it has to work on a live process.
    """
    overrides: dict[str, object] = {}

    raw = os.getenv(cfg.budget_env_var)
    if raw:
        try:
            value = int(raw)
        except ValueError:
            pass
        else:
            if value > 0:
                overrides["max_prompt_tokens"] = value

    model = (os.getenv(cfg.model_env_var) or "").strip()
    if model:
        overrides["model"] = model

    return replace(cfg, **overrides) if overrides else cfg
