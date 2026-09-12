import hashlib
import hmac

from mergency.adapters.github.signature import verify_signature

SECRET = "test-webhook-secret"


def _signature_for(payload: bytes, secret: str = SECRET) -> str:
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def test_valid_signature_is_accepted():
    payload = b'{"action": "created"}'
    signature = _signature_for(payload)

    assert verify_signature(payload, signature, SECRET) is True


def test_tampered_payload_is_rejected():
    payload = b'{"action": "created"}'
    signature = _signature_for(payload)
    tampered_payload = b'{"action": "deleted"}'

    assert verify_signature(tampered_payload, signature, SECRET) is False


def test_missing_signature_header_is_rejected():
    payload = b'{"action": "created"}'

    assert verify_signature(payload, None, SECRET) is False


def test_malformed_signature_header_is_rejected():
    payload = b'{"action": "created"}'
    digest = hmac.new(SECRET.encode(), payload, hashlib.sha256).hexdigest()

    assert verify_signature(payload, digest, SECRET) is False
