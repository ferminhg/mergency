from mergency.domain.models.pull_request_signal import PullRequestSignal


def parse_pull_request_signal(payload: dict) -> PullRequestSignal:
    return PullRequestSignal(
        installation_id=payload["installation"]["id"],
        repo=payload["repository"]["full_name"],
        pr_number=payload["number"],
        action=payload["action"],
    )
