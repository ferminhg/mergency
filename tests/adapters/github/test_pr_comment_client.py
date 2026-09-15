from unittest.mock import MagicMock

from mergency.adapters.github.pr_comment_client import GithubPrCommentClient
from mergency.domain.pr_comment_formatter import MARKER


class _StubTokenProvider:
    async def get_token(self, installation_id: int) -> str:
        return "test-token"


def _client() -> GithubPrCommentClient:
    return GithubPrCommentClient(_StubTokenProvider())


async def test_find_marked_comment_returns_the_id_of_the_matching_comment(monkeypatch):
    marked_comment = MagicMock(id=999, body=f"{MARKER}\nold status")
    other_comment = MagicMock(id=1, body="unrelated comment")
    client = MagicMock()
    client.get_repo.return_value.get_issue.return_value.get_comments.return_value = [
        other_comment,
        marked_comment,
    ]
    monkeypatch.setattr("mergency.adapters.github.pr_comment_client.Github", lambda **kwargs: client)

    comment_id = await _client().find_marked_comment(1, "acme/widgets", 42)

    assert comment_id == 999


async def test_find_marked_comment_returns_none_when_no_comment_carries_the_marker(monkeypatch):
    client = MagicMock()
    client.get_repo.return_value.get_issue.return_value.get_comments.return_value = [
        MagicMock(id=1, body="unrelated comment")
    ]
    monkeypatch.setattr("mergency.adapters.github.pr_comment_client.Github", lambda **kwargs: client)

    comment_id = await _client().find_marked_comment(1, "acme/widgets", 42)

    assert comment_id is None


async def test_create_comment_posts_the_body_on_the_pull_request_issue(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr("mergency.adapters.github.pr_comment_client.Github", lambda **kwargs: client)

    await _client().create_comment(1, "acme/widgets", 42, "hello")

    client.get_repo.assert_called_once_with("acme/widgets")
    client.get_repo.return_value.get_issue.assert_called_once_with(42)
    client.get_repo.return_value.get_issue.return_value.create_comment.assert_called_once_with("hello")


async def test_update_comment_edits_the_comment_by_id(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr("mergency.adapters.github.pr_comment_client.Github", lambda **kwargs: client)

    await _client().update_comment(1, "acme/widgets", 999, "updated body")

    client.get_repo.return_value.get_issue_comment.assert_called_once_with(999)
    client.get_repo.return_value.get_issue_comment.return_value.edit.assert_called_once_with(
        "updated body"
    )
