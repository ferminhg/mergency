import hashlib
import hmac

_SIGNATURE_PREFIX = "sha256="


def verify_signature(payload: bytes, signature_header: str | None, secret: str) -> bool:
    if signature_header is None or not signature_header.startswith(_SIGNATURE_PREFIX):
        return False

    expected_digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    expected_header = f"{_SIGNATURE_PREFIX}{expected_digest}"

    return hmac.compare_digest(expected_header, signature_header)
