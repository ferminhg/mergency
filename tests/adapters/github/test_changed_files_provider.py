from unittest.mock import MagicMock

from mergency.adapters.github.changed_files_provider import GithubChangedFilesProvider


class _StubTokenProvider:
    async def get_token(self, installation_id: int) -> str:
        return "test-token"


async def test_returns_filenames_from_the_commit(monkeypatch):
    provider = GithubChangedFilesProvider(_StubTokenProvider())
    file_a = MagicMock(filename="src/a.py")
    file_b = MagicMock(filename="src/b.py")
    client = MagicMock()
    client.get_repo.return_value.get_commit.return_value.files = [file_a, file_b]
    monkeypatch.setattr(
        "mergency.adapters.github.changed_files_provider.Github", lambda **kwargs: client
    )

    files = await provider.files_changed_in_commit(1, "acme/widgets", "abc123")

    assert files == ["src/a.py", "src/b.py"]
    client.get_repo.assert_called_once_with("acme/widgets")
    client.get_repo.return_value.get_commit.assert_called_once_with("abc123")
