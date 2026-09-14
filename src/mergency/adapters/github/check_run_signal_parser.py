from datetime import datetime

from mergency.domain.models.check_run_signal import CheckRunSignal


def parse_check_run_signal(payload: dict) -> CheckRunSignal:
    check_run = payload["check_run"]
    repository = payload["repository"]
    completed_at = check_run["completed_at"]

    return CheckRunSignal(
        installation_id=payload["installation"]["id"],
        repo=repository["full_name"],
        sha=check_run["head_sha"],
        action=payload["action"],
        conclusion=check_run["conclusion"],
        head_branch=check_run["check_suite"]["head_branch"],
        default_branch=repository["default_branch"],
        completed_at=datetime.fromisoformat(completed_at) if completed_at else None,
    )
