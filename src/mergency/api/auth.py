import secrets

from mergency.domain.models.installation import Installation

_BEARER_PREFIX = "Bearer "


def token_matches(installation: Installation, authorization_header: str | None) -> bool:
    if installation.api_token is None:
        return False
    if authorization_header is None or not authorization_header.startswith(_BEARER_PREFIX):
        return False
    presented_token = authorization_header[len(_BEARER_PREFIX) :]
    return secrets.compare_digest(presented_token, installation.api_token)
