from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass
class NormalizedRepoURL:
  owner: str
  name: str


class RepoURLValidationError(Exception):
  def __init__(self, message: str):
    super().__init__(message)
    self.message = message


def normalize_github_repo_url(repo_url: str) -> NormalizedRepoURL:
  """
  Validate and normalize a GitHub repository URL into owner and name.

  Expected forms:
  - https://github.com/owner/repo
  - https://github.com/owner/repo/
  """
  if not repo_url:
    raise RepoURLValidationError("Repository URL is required.")

  parsed = urlparse(repo_url.strip())
  if parsed.scheme not in {"http", "https"}:
    raise RepoURLValidationError("Repository URL must start with http:// or https://.")

  if parsed.netloc.lower() != "github.com":
    raise RepoURLValidationError("Only github.com repository URLs are supported in v0.1.")

  # path like /owner/repo or /owner/repo/
  path_parts = [p for p in parsed.path.split("/") if p]
  if len(path_parts) < 2:
    raise RepoURLValidationError("Repository URL must be of the form https://github.com/owner/repo.")

  owner, name = path_parts[0], path_parts[1]
  if not owner or not name:
    raise RepoURLValidationError("Repository owner and name could not be determined from URL.")

  return NormalizedRepoURL(owner=owner, name=name)