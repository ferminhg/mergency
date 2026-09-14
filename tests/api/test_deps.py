from mergency.api import deps


def _set_required_env(monkeypatch, app_id: str) -> None:
    monkeypatch.setenv("MERGENCY_GITHUB_APP_ID", app_id)
    monkeypatch.setenv("MERGENCY_GITHUB_PRIVATE_KEY", "test-private-key")
    monkeypatch.setenv("MERGENCY_GITHUB_WEBHOOK_SECRET", "test-webhook-secret")


def test_get_settings_reflects_env_change_after_cache_clear(monkeypatch):
    _set_required_env(monkeypatch, "first-app-id")
    assert deps.get_settings().github_app_id == "first-app-id"

    deps.reset_dependency_caches()
    _set_required_env(monkeypatch, "second-app-id")
    assert deps.get_settings().github_app_id == "second-app-id"


def test_get_installation_token_provider_rebuilds_from_current_settings_after_cache_clear(
    monkeypatch,
):
    captured_app_ids = []

    class _FakeProvider:
        def __init__(self, app_id, private_key):
            captured_app_ids.append(app_id)

    monkeypatch.setattr(deps, "PyGithubInstallationTokenProvider", _FakeProvider)

    _set_required_env(monkeypatch, "first-app-id")
    deps.get_installation_token_provider()

    deps.reset_dependency_caches()
    _set_required_env(monkeypatch, "second-app-id")
    deps.get_installation_token_provider()

    assert captured_app_ids == ["first-app-id", "second-app-id"]


def test_get_event_classifier_is_cached_and_resettable():
    from mergency.api import deps

    first = deps.get_event_classifier()
    assert deps.get_event_classifier() is first

    deps.reset_dependency_caches()

    assert deps.get_event_classifier() is not first
