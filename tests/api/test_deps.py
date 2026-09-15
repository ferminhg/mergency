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


def test_ownership_resolution_dependencies_are_cached_and_resettable(monkeypatch):
    _set_required_env(monkeypatch, "test-app-id")
    factories = [
        deps.get_tenant_config_repository,
        deps.get_repository_content_provider,
        deps.get_codeowners_provider,
        deps.get_changed_files_provider,
        deps.get_config_resolver,
        deps.get_ownership_resolver,
    ]
    first_instances = [factory() for factory in factories]

    assert [factory() for factory in factories] == first_instances

    deps.reset_dependency_caches()

    assert all(
        factory() is not first
        for factory, first in zip(factories, first_instances, strict=True)
    )


def test_get_budget_calculator_is_cached_and_resettable():
    from mergency.api import deps

    first = deps.get_budget_calculator()
    assert deps.get_budget_calculator() is first

    deps.reset_dependency_caches()

    assert deps.get_budget_calculator() is not first


def test_event_repository_is_sqlalchemy_backed():
    from mergency.adapters.db.event_repository import SqlAlchemyEventRepository
    from mergency.api import deps

    assert isinstance(deps.get_event_repository(), SqlAlchemyEventRepository)


def test_tenant_config_repository_is_sqlalchemy_backed():
    from mergency.adapters.db.tenant_config_repository import SqlAlchemyTenantConfigRepository
    from mergency.api import deps

    assert isinstance(deps.get_tenant_config_repository(), SqlAlchemyTenantConfigRepository)
