from mergency.api.auth import token_matches
from mergency.domain.models.installation import Installation
from mergency.domain.models.tenant_status import TenantStatus


def _installation(api_token: str | None = "the-real-token") -> Installation:
    return Installation(
        installation_id=42,
        account_login="acme",
        account_type="Organization",
        status=TenantStatus.ACTIVE,
        repository_selection="all",
        api_token=api_token,
    )


def test_token_matches_accepts_the_correct_bearer_token():
    assert token_matches(_installation(), "Bearer the-real-token") is True


def test_token_matches_rejects_a_wrong_token():
    assert token_matches(_installation(), "Bearer wrong-token") is False


def test_token_matches_rejects_a_missing_header():
    assert token_matches(_installation(), None) is False


def test_token_matches_rejects_a_header_without_the_bearer_prefix():
    assert token_matches(_installation(), "the-real-token") is False


def test_token_matches_rejects_when_installation_has_no_token_minted():
    assert token_matches(_installation(api_token=None), "Bearer anything") is False
