from unittest.mock import MagicMock

from mergency.adapters.github.commit_range_provider import GithubCommitRangeProvider


class _StubTokenProvider:
    async def get_token(self, installation_id: int) -> str:
        return "test-token"


async def test_returns_shas_of_every_commit_in_the_range(monkeypatch):
    provider = GithubCommitRangeProvider(_StubTokenProvider())
    commit_a = MagicMock(sha="sha-a")
    commit_b = MagicMock(sha="sha-b")
    client = MagicMock()
    client.get_repo.return_value.compare.return_value.commits = [commit_a, commit_b]
    monkeypatch.setattr(
        "mergency.adapters.github.commit_range_provider.Github", lambda **kwargs: client
    )

    shas = await provider.commits_between(1, "acme/widgets", "base123", "head456")

    assert shas == ["sha-a", "sha-b"]
    client.get_repo.assert_called_once_with("acme/widgets")
    client.get_repo.return_value.compare.assert_called_once_with("base123", "head456")


async def test_returns_the_single_sha_when_base_and_head_are_identical(monkeypatch):
    provider = GithubCommitRangeProvider(_StubTokenProvider())
    client = MagicMock()
    monkeypatch.setattr(
        "mergency.adapters.github.commit_range_provider.Github", lambda **kwargs: client
    )

    shas = await provider.commits_between(1, "acme/widgets", "same-sha", "same-sha")

    assert shas == ["same-sha"]
    client.get_repo.assert_not_called()
