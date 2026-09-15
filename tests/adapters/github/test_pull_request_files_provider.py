from unittest.mock import MagicMock

from mergency.adapters.github.pull_request_files_provider import GithubPullRequestFilesProvider


class _StubTokenProvider:
    async def get_token(self, installation_id: int) -> str:
        return "test-token"


async def test_returns_filenames_from_the_pull_request(monkeypatch):
    provider = GithubPullRequestFilesProvider(_StubTokenProvider())
    file_a = MagicMock(filename="src/a.py")
    file_b = MagicMock(filename="src/b.py")
    client = MagicMock()
    client.get_repo.return_value.get_pull.return_value.get_files.return_value = [file_a, file_b]
    monkeypatch.setattr(
        "mergency.adapters.github.pull_request_files_provider.Github", lambda **kwargs: client
    )

    files = await provider.files_changed_in_pull_request(1, "acme/widgets", 42)

    assert files == ["src/a.py", "src/b.py"]
    client.get_repo.assert_called_once_with("acme/widgets")
    client.get_repo.return_value.get_pull.assert_called_once_with(42)
