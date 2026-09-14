from datetime import datetime

from mergency.domain.models.push_commit import PushCommit
from mergency.domain.models.push_signal import PushSignal


def parse_push_signal(payload: dict) -> PushSignal:
    repository = payload["repository"]
    commits = [
        PushCommit(
            sha=commit["id"],
            message=commit["message"],
            timestamp=datetime.fromisoformat(commit["timestamp"]),
            files=[
                *commit.get("added", []),
                *commit.get("removed", []),
                *commit.get("modified", []),
            ],
        )
        for commit in payload["commits"]
    ]

    return PushSignal(
        installation_id=payload["installation"]["id"],
        repo=repository["full_name"],
        ref=payload["ref"],
        default_branch=repository["default_branch"],
        commits=commits,
    )
