import dataclasses
from datetime import datetime, timezone

import pytest

from mergency.domain.models.incident_report import IncidentReport


def _report(severity: str | None = None) -> IncidentReport:
    return IncidentReport(
        installation_id=1,
        repo="acme/widgets",
        base_sha="base123",
        head_sha="head456",
        severity=severity,
        occurred_at=datetime.now(timezone.utc),
    )


def test_incident_report_holds_the_reported_commit_range_and_severity():
    report = _report(severity="P1")

    assert report.repo == "acme/widgets"
    assert report.base_sha == "base123"
    assert report.head_sha == "head456"
    assert report.severity == "P1"


def test_severity_is_optional():
    report = _report(severity=None)

    assert report.severity is None


def test_incident_report_is_immutable():
    report = _report()

    with pytest.raises(dataclasses.FrozenInstanceError):
        report.head_sha = "other"
