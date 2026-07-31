from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class GitHubConfig:
    api_base_url: str = "https://api.github.com"
    api_version: str = "2022-11-28"  # GitHub API version header
    token_env_var: str = "REPOBRIDGE_GITHUB_TOKEN"


def get_github_token() -> str | None:
    """
    Return the GitHub token from environment if set, otherwise None.
    v0.1 keeps this very simple: no secret storage, just an env variable.
    """
    return os.getenv(GitHubConfig().token_env_var)