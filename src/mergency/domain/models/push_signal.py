from dataclasses import dataclass

from mergency.domain.models.push_commit import PushCommit


@dataclass(frozen=True)
class PushSignal:
    installation_id: int
    repo: str
    ref: str
    default_branch: str
    commits: list[PushCommit]
