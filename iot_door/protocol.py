"""HMAC-signed IoT camera messages and in-memory demo guards."""
from __future__ import annotations

import hashlib
import hmac
import re
import threading
import time

NONCE_PATTERN = re.compile(r"^[0-9a-f]{32}$")
SIGNATURE_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def capture_signature(secret: str, device_id: str, timestamp: int,
                      nonce: str, jpeg: bytes) -> str:
    image_sha = hashlib.sha256(jpeg).hexdigest()
    message = f"{device_id}\n{timestamp}\n{nonce}\n{image_sha}".encode("ascii")
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def valid_capture_signature(secret: str, device_id: str, timestamp: str,
                            nonce: str, jpeg: bytes, signature: str,
                            *, now: int | None = None, skew_seconds: int = 15) -> bool:
    if (len(secret) < 32 or not device_id.isascii() or not timestamp.isdecimal()
            or not NONCE_PATTERN.fullmatch(nonce)
            or not SIGNATURE_PATTERN.fullmatch(signature)):
        return False
    current = int(time.time()) if now is None else now
    ts = int(timestamp)
    if abs(current - ts) > skew_seconds:
        return False
    return hmac.compare_digest(
        capture_signature(secret, device_id, ts, nonce, jpeg), signature
    )


def response_signature(secret: str, raw_body: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()


class ReplayWindow:
    """Single-process guard. Persistent replay defense is future work."""

    def __init__(self):
        self._lock = threading.Lock()
        self._used: dict[tuple[str, str], int] = {}

    def claim(self, device_id: str, nonce: str, *, now: int | None = None,
              ttl_seconds: int = 30) -> bool:
        current = int(time.time()) if now is None else now
        with self._lock:
            self._used = {key: expiry for key, expiry in self._used.items()
                          if expiry > current}
            key = (device_id, nonce)
            if key in self._used or len(self._used) >= 4096:
                return False
            self._used[key] = current + ttl_seconds
            return True


class ConfirmationGate:
    """Same person in multiple distinct frames, time bound and cooled down."""

    def __init__(self):
        self._lock = threading.Lock()
        self._observations: dict[str, tuple[int, float, set[str]]] = {}
        self._cooldown: dict[str, float] = {}

    def reset(self, device_id: str) -> None:
        with self._lock:
            self._observations.pop(device_id, None)

    def observe(self, device_id: str, subject_id: int, jpeg: bytes, *,
                minimum_hits: int = 3, window_seconds: float = 8,
                cooldown_seconds: float = 5, now: float | None = None) -> str:
        current = time.monotonic() if now is None else now
        fingerprint = hashlib.sha256(jpeg).hexdigest()
        with self._lock:
            if self._cooldown.get(device_id, 0) > current:
                return "cooldown"
            previous = self._observations.get(device_id)
            if (previous is None or previous[0] != subject_id
                    or current - previous[1] > window_seconds):
                first = current
                seen = set()
            else:
                first, seen = previous[1], previous[2]
            seen.add(fingerprint)
            if len(seen) < minimum_hits:
                self._observations[device_id] = (subject_id, first, seen)
                return "pending"
            self._observations.pop(device_id, None)
            self._cooldown[device_id] = current + cooldown_seconds
            return "unlock"
