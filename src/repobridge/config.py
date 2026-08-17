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