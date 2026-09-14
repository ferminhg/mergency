import pytest

from mergency.api.deps import reset_dependency_caches


@pytest.fixture(autouse=True)
def _reset_dependency_caches():
    yield
    reset_dependency_caches()
