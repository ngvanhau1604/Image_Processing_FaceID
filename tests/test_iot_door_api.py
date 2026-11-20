"""Contract tests for IoT endpoint with fake recognition and audit database."""
import hmac
import time
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app import iot_door
from backend.app.database import get_db
from iot_door.protocol import (
    ConfirmationGate, ReplayWindow, capture_signature, response_signature,
)

SECRET = "0123456789abcdef0123456789abcdef"
DEVICE = "door-demo-01"


class DummyDb:
    def __init__(self):
        self.events = []

    def add(self, event):
        self.events.append(event)

    def commit(self):
        pass

    def rollback(self):
        pass


def make_client(monkeypatch, *, enabled=True, allowed="1"):
    settings = SimpleNamespace(
        iot_door_enabled=enabled,
        iot_door_device_id=DEVICE,
        iot_door_hmac_secret=SECRET,
        iot_door_allowed_student_ids=allowed,
        iot_door_min_hits=3,
        iot_door_unlock_ms=2000,
    )
    monkeypatch.setattr(iot_door, "get_settings", lambda: settings)
    monkeypatch.setattr(iot_door, "_replay", ReplayWindow())
    monkeypatch.setattr(iot_door, "_gate", ConfirmationGate())
    monkeypatch.setattr(iot_door, "_identify", lambda db, image, subjects: (1, "recognized"))
    db = DummyDb()
    app = FastAPI()
    app.include_router(iot_door.router)
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app), db


def signed_headers(image, nonce, *, timestamp=None):
    when = int(time.time()) if timestamp is None else timestamp
    return {
        "Content-Type": "image/jpeg",
        "X-Device-ID": DEVICE,
        "X-Timestamp": str(when),
        "X-Nonce": nonce,
        "X-Signature": capture_signature(SECRET, DEVICE, when, nonce, image),
    }


def test_disabled_or_no_allowlist(monkeypatch):
    client, _ = make_client(monkeypatch, enabled=False)
    image = b"\xff\xd8sample\xff\xd9"
    assert client.post("/iot/door/capture", content=image,
                       headers=signed_headers(image, "0" * 32)).status_code == 503
    client, _ = make_client(monkeypatch, allowed="")
    assert client.post("/iot/door/capture", content=image,
                       headers=signed_headers(image, "1" * 32)).status_code == 503


def test_bad_hmac_replay_and_confirmed_unlock(monkeypatch):
    client, db = make_client(monkeypatch)
    first = b"\xff\xd8image-1\xff\xd9"
    nonce = "1" * 32
    headers = signed_headers(first, nonce)
    bad = dict(headers, **{"X-Signature": "0" * 64})
    assert client.post("/iot/door/capture", content=first, headers=bad).status_code == 401
    response = client.post("/iot/door/capture", content=first, headers=headers)
    assert response.status_code == 200
    assert response.json()["decision"] == "pending"
    assert response.json()["unlock_ms"] == 0
    assert hmac.compare_digest(
        response_signature(SECRET, response.content),
        response.headers["X-Door-Response-Signature"],
    )
    assert client.post("/iot/door/capture", content=first, headers=headers).status_code == 409

    second = b"\xff\xd8image-2\xff\xd9"
    third = b"\xff\xd8image-3\xff\xd9"
    r2 = client.post("/iot/door/capture", content=second,
                     headers=signed_headers(second, "2" * 32))
    r3 = client.post("/iot/door/capture", content=third,
                     headers=signed_headers(third, "3" * 32))
    assert r2.json()["decision"] == "pending"
    assert r3.json()["decision"] == "unlock"
    assert r3.json()["unlock_ms"] == 2000
    assert r3.json()["request_nonce"] == "3" * 32
    assert len(db.events) == 3


def test_same_frame_does_not_count_as_new_evidence(monkeypatch):
    client, _ = make_client(monkeypatch)
    image = b"\xff\xd8same-frame\xff\xd9"
    decisions = [
        client.post("/iot/door/capture", content=image,
                    headers=signed_headers(image, f"{n:032x}")).json()["decision"]
        for n in (4, 5, 6)
    ]
    assert decisions == ["pending", "pending", "pending"]


def test_frame_limit_and_content_type(monkeypatch):
    client, _ = make_client(monkeypatch)
    image = b"\xff\xd8" + b"X" * 250_000 + b"\xff\xd9"
    result = client.post("/iot/door/capture", content=image,
                         headers=signed_headers(image, "7" * 32))
    assert result.status_code == 413
    small = b"\xff\xd8foo\xff\xd9"
    headers = signed_headers(small, "8" * 32)
    headers["Content-Type"] = "text/plain"
    assert client.post("/iot/door/capture", content=small, headers=headers).status_code == 415
