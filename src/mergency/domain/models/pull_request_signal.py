from dataclasses import dataclass


@dataclass(frozen=True)
class PullRequestSignal:
    installation_id: int
    repo: str
    pr_number: int
    action: str
