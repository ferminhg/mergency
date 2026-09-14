from unittest.mock import MagicMock

from github.GithubException import UnknownObjectException

from mergency.adapters.github.repository_content_provider import GithubRepositoryContentProvider


class _StubTokenProvider:
    async def get_token(self, installation_id: int) -> str:
        return "test-token"


def _provider() -> GithubRepositoryContentProvider:
    return GithubRepositoryContentProvider(_StubTokenProvider())


async def test_get_file_returns_decoded_content(monkeypatch):
    provider = _provider()
    content_file = MagicMock()
    content_file.decoded_content = b"rolling_window_days: 14\n"
    client = MagicMock()
    client.get_repo.return_value.get_contents.return_value = content_file
    monkeypatch.setattr(
        "mergency.adapters.github.repository_content_provider.Github", lambda **kwargs: client
    )

    text = await provider.get_file(1, "acme/widgets", "mergency.yml")

    assert text == "rolling_window_days: 14\n"
    client.get_repo.assert_called_once_with("acme/widgets")
    client.get_repo.return_value.get_contents.assert_called_once_with("mergency.yml")


async def test_get_file_returns_none_when_missing(monkeypatch):
    provider = _provider()
    client = MagicMock()
    client.get_repo.return_value.get_contents.side_effect = UnknownObjectException(
        404, data="Not Found"
    )
    monkeypatch.setattr(
        "mergency.adapters.github.repository_content_provider.Github", lambda **kwargs: client
    )

    text = await provider.get_file(1, "acme/widgets", "mergency.yml")

    assert text is None
