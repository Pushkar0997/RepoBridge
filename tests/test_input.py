from repobridge.core.input import normalize_github_repo_url, RepoURLValidationError


def test_normalize_valid_github_url():
  url = "https://github.com/owner/repo"
  result = normalize_github_repo_url(url)
  assert result.owner == "owner"
  assert result.name == "repo"


def test_normalize_valid_github_url_with_trailing_slash():
  url = "https://github.com/owner/repo/"
  result = normalize_github_repo_url(url)
  assert result.owner == "owner"
  assert result.name == "repo"


def test_normalize_rejects_non_github_domain():
  url = "https://gitlab.com/owner/repo"
  try:
    normalize_github_repo_url(url)
    assert False, "Expected RepoURLValidationError"
  except RepoURLValidationError as e:
    assert "github.com" in e.message


def test_normalize_rejects_missing_owner_or_repo():
  bad_urls = [
    "https://github.com/",
    "https://github.com/owner",
    "https://github.com//",
  ]
  for url in bad_urls:
    try:
      normalize_github_repo_url(url)
      assert False, f"Expected error for {url}"
    except RepoURLValidationError:
      pass