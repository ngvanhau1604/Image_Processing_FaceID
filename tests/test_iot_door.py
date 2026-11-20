"""Protocol tests require no camera, ML runtime or hardware."""
import hashlib
import hmac

from iot_door.protocol import (
    ConfirmationGate, ReplayWindow, capture_signature, response_signature,
    valid_capture_signature,
)

KEY = "0123456789abcdef0123456789abcdef"
DEVICE = "door-demo-01"
NONCE = "0123456789abcdef0123456789abcdef"
JPEG = b"\xff\xd8fresh-frame\xff\xd9"


def test_hmac_roundtrip_tampering_timestamp_and_wrong_secret():
    sig = capture_signature(KEY, DEVICE, 1234567890, NONCE, JPEG)
    assert valid_capture_signature(KEY, DEVICE, "1234567890", NONCE, JPEG,
                                   sig, now=1234567890)
    assert not valid_capture_signature(KEY, DEVICE, "1234567890", NONCE,
                                       JPEG + b"x", sig, now=1234567890)
    assert not valid_capture_signature(KEY, DEVICE, "1234567890", NONCE,
                                       JPEG, "0" * 64, now=1234567890)
    assert not valid_capture_signature(KEY, DEVICE, "1234567890", NONCE,
                                       JPEG, sig, now=1234567906)
    assert not valid_capture_signature("short", DEVICE, "1234567890", NONCE,
                                       JPEG, sig, now=1234567890)


def test_signed_response():
    body = b'{"decision":"denied","unlock_ms":0}'
    assert response_signature(KEY, body) == hmac.new(
        KEY.encode(), body, hashlib.sha256
    ).hexdigest()


def test_replay():
    guard = ReplayWindow()
    assert guard.claim(DEVICE, NONCE, now=100)
    assert not guard.claim(DEVICE, NONCE, now=100)
    assert guard.claim(DEVICE, NONCE, now=131)


def test_distinct_frames_same_identity_and_cooldown():
    gate = ConfirmationGate()
    assert gate.observe(DEVICE, 10, b"a", now=100) == "pending"
    assert gate.observe(DEVICE, 10, b"a", now=101) == "pending"
    assert gate.observe(DEVICE, 11, b"b", now=102) == "pending"
    assert gate.observe(DEVICE, 11, b"c", now=103) == "pending"
    assert gate.observe(DEVICE, 11, b"d", now=104) == "unlock"
    assert gate.observe(DEVICE, 11, b"e", now=105) == "cooldown"
    assert gate.observe(DEVICE, 11, b"f", now=110) == "pending"


def test_confirmation_window_expiration():
    gate = ConfirmationGate()
    assert gate.observe(DEVICE, 10, b"a", now=10) == "pending"
    assert gate.observe(DEVICE, 10, b"b", now=19) == "pending"
    assert gate.observe(DEVICE, 10, b"c", now=20) == "pending"
