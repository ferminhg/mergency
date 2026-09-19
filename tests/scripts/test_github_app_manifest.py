import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "github_app_manifest", Path(__file__).parents[2] / "scripts" / "github_app_manifest.py"
)
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


def test_manifest_requests_issues_write_permission():
    manifest = _MODULE._build_manifest("https://example.com/webhooks/github", "mergency-dev")

    assert manifest["default_permissions"]["issues"] == "write"
