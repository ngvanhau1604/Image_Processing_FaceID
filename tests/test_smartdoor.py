import secrets
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from smartdoor.evaluate import calibrate, fit, summarize
from smartdoor.hardware import PIN_NAMES, board_pins, prepare_firmware, make_tls
from smartdoor.protocol import ACK, VERIFY, Pending, Ticket
from smartdoor.server import create_app
from smartdoor.setup import provision
from smartdoor.storage import data_directory, now_ms
from smartdoor.vision import Observation, PROFILE, Vision


class FixtureVision:
    def observe(self, body):
        if body in (b"no_face", b"multiple_faces", b"ai_unavailable", b"blurry", b"invalid_jpeg"):
            return Observation(body.decode())
        vector = np.zeros(128, dtype="<f4")
        vector[1 if body.startswith(b"stranger") else 0] = 1
        return Observation("face", vector.tobytes())


class Lab:
    def __init__(self, app, client):
        self.app, self.client = app, client
        self.device = "webcam-demo"
        self.boot = secrets.token_hex(16)
        self.store = app.state.store
        self.keys = {}
        with self.store.transaction(False) as db:
            self.keys = dict(db.execute("SELECT id,secret FROM devices"))

    def post(self, path, body, ticket=None, headers=None):
        ticket = ticket or Ticket.new(self.device, self.boot)
        return self.client.post(
            path, content=body, headers=headers or ticket.headers(self.keys[self.device], path, body)
        )

    def scan(self, body):
        ticket = Ticket.new(self.device, self.boot)
        response = self.post(VERIFY, body, ticket)
        assert response.status_code == 200, response.text
        return (*Pending(ticket).consume(self.keys[self.device], response.text), ticket)

    def admin(self, path, method="GET", body=None):
        return self.client.request(method, "/api/v1/" + path, json=body)

    def enroll(self):
        person = self.admin("people", "POST", {"code": "A", "name": "An", "consent": True}).json()["id"]
        assert self.admin("enrollments", "POST", {"device": self.device, "person": person}).status_code == 201
        for i in range(5):
            assert self.scan(f"sample-{i}".encode())[0] == "DENIED"
        return person

    def clear(self):
        self.scan(b"no_face")
        with self.store.transaction() as db:
            db.execute("UPDATE devices SET empty_since=? WHERE id=?", (now_ms() - 1200, self.device))
        self.scan(b"no_face")


@pytest.fixture
def lab(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app, base_url="https://testserver") as client:
        provision(app.state.store, "admin", "testing-only-pass")
        assert (
            client.post(
                "/api/v1/login", json={"username": "admin", "password": "testing-only-pass"}
            ).status_code
            == 200
        )
        app.state.vision = FixtureVision()
        yield Lab(app, client)


def test_authorized_unknown_revoked_and_receipts(lab):
    person = lab.enroll()
    lab.clear()
    assert lab.admin(f"people/{person}/permission", "PUT", {"device": lab.device, "allowed": True}).is_success
    decision, reason, ticket = lab.scan(b"sample")
    assert (decision, reason) == ("GRANTED", "authorized")
    assert lab.scan(b"sample")[1] == "wait_until_clear"
    assert lab.post(VERIFY, b"sample", ticket).status_code == 409
    for state, ms in (("started", 0), ("stopped", 2000), ("started", 0)):
        assert lab.post(ACK, f"{ticket.request}\n{state}\n{ms}".encode()).is_success
    lab.boot = secrets.token_hex(16)
    assert lab.scan(b"sample")[1] == "wait_until_clear"
    assert lab.post(ACK, f"{ticket.request}\nstopped\n2000".encode()).status_code == 404
    lab.clear()
    assert lab.scan(b"stranger")[:2] == ("DENIED", "unknown")
    assert lab.admin(
        f"people/{person}/permission", "PUT", {"device": lab.device, "allowed": False}
    ).is_success
    assert lab.scan(b"sample")[:2] == ("DENIED", "permission_denied")
    event = next(e for e in lab.admin("access/events").json() if e["request"] == ticket.request)
    assert event["execution"] == "stopped" and event["pulse_ms"] == 2000


def test_renew_enrollment_abort_consent_and_manual(lab):
    person = lab.enroll()
    assert lab.admin("enrollments", "POST", {"device": lab.device, "person": person}).is_success
    lab.scan(b"other")
    assert lab.scan(b"other")[1] == "duplicate_sample"
    assert lab.admin("access/manual-unlock", "POST", {"device": lab.device}).status_code == 409
    assert lab.admin("enrollments/" + lab.device, "DELETE").is_success
    assert lab.admin("people").json()[0]["samples"] == 5
    assert lab.admin("access/manual-unlock", "POST", {"device": lab.device}).is_success
    assert lab.scan(b"no_face")[:2] == ("GRANTED", "manual")
    assert lab.admin("access/events").json()[0]["execution"] == "pending"
    assert lab.scan(b"no_face")[0] == "DENIED"
    assert lab.admin("enrollments", "POST", {"device": lab.device, "person": person}).status_code == 409
    with lab.store.transaction() as db:
        db.execute("UPDATE events SET time=time-6000 WHERE decision='GRANTED'")
    assert lab.admin(f"people/{person}/permission", "PUT", {"device": lab.device, "allowed": True}).is_success
    assert lab.admin("enrollments", "POST", {"device": lab.device, "person": person}).is_success
    lab.scan(b"partial")
    assert lab.admin(f"people/{person}", "PUT", {"name": "An", "code": "A", "consent": False}).is_success
    with lab.store.transaction(False) as db:
        for table in ("templates", "drafts", "enrollments", "permissions"):
            assert db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


@pytest.mark.parametrize("reason", ["multiple_faces", "blurry", "invalid_jpeg", "ai_unavailable"])
def test_fail_closed_conditions(lab, reason):
    assert lab.scan(reason.encode())[0] in {"DENIED", "ERROR"}


def test_authenticated_and_bounded(lab):
    ticket = Ticket.new(lab.device, lab.boot)
    headers = ticket.headers(lab.keys[lab.device], VERIFY, b"a")
    assert lab.post(VERIFY, b"b", headers=headers).status_code == 401
    assert lab.post(VERIFY, b"x" * 1_000_001).status_code == 413
    expired = Ticket(ticket.device, ticket.boot, ticket.request, ticket.nonce, now_ms() - 7000)
    assert lab.post(VERIFY, b"a", expired).status_code == 401
    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = list(pool.map(lambda _: lab.post(VERIFY, b"a", ticket).status_code, range(2)))
    assert sorted(codes) == [200, 409]
    lab.client.cookies.clear()
    assert lab.admin("devices/health").status_code == 401
    assert lab.admin("enrollments", "POST", {"device": lab.device, "person": 1}).status_code == 401


def test_pending_bound_to_challenge_and_consumed(lab):
    ticket = Ticket.new(lab.device, lab.boot)
    response = lab.post(VERIFY, b"no_face", ticket).text
    pending = Pending(ticket)
    assert pending.consume(lab.keys[lab.device], response)[0] == "DENIED"
    with pytest.raises(ValueError):
        pending.consume(lab.keys[lab.device], response)
    with pytest.raises(ValueError):
        Pending(Ticket.new(lab.device, lab.boot)).consume(lab.keys[lab.device], response)
    with pytest.raises(ValueError):
        Pending(ticket).consume(lab.keys[lab.device], response.replace("DENIED", "GRANTED"))
    from smartdoor.protocol import response_text

    expired = response_text(lab.keys[lab.device], ticket, "GRANTED", "authorized", now_ms() - 1)
    with pytest.raises(ValueError):
        Pending(ticket).consume(lab.keys[lab.device], expired)


def test_hardware_requires_calibration_and_tls(lab, tmp_path):
    lab.device = "door-kit"
    person = lab.enroll()
    lab.clear()
    lab.admin(f"people/{person}/permission", "PUT", {"device": lab.device, "allowed": True})
    a = lab.scan(b"sample")
    b = lab.scan(b"stranger")
    assert a[1] == b[1] == "calibration_required"
    manifest = tmp_path / "labels.csv"
    manifest.write_text(
        f"request,expected_code,session\n{a[2].request},A,visit2\n{b[2].request},UNKNOWN,visit2\n"
    )
    report = calibrate(lab.store, lab.device, manifest, True)
    assert report["samples"] == 2 and lab.scan(b"sample")[0] == "GRANTED"
    ticket = Ticket.new(lab.device, lab.boot)
    result = lab.client.post(
        "http://testserver" + VERIFY,
        content=b"sample",
        headers=ticket.headers(lab.keys[lab.device], VERIFY, b"sample"),
    )
    assert result.status_code == 401


def test_hardware_provision_and_private_data(lab, tmp_path, monkeypatch):
    with pytest.raises(ValueError):
        board_pins({"sensor": "OV3660"}, True)
    mapping = dict(zip(PIN_NAMES, [11, 9, 8, 10, 12, 18, 17, 16, 15, 13, 6, 7, 4, 5, -1, -1]))
    profile = dict(
        sensor="OV3660",
        pinout_source="synthetic compilation fixture",
        camera=mapping,
        relay=dict(gpio=4, active_high=True),
    )
    with pytest.raises(ValueError):
        board_pins(profile, True)
    make_tls(tmp_path, "127.0.0.1")
    folder = prepare_firmware(
        lab.store, profile, "https://127.0.0.1:8443", "fixture", "private-wifi", "127.0.0.1"
    )
    assert "RELAY_PIN = -1" in (folder / "private_config.h").read_text()
    monkeypatch.setenv("SMARTDOOR_HOME", str(Path(__file__).resolve().parent / "private"))
    with pytest.raises(ValueError):
        data_directory()


def test_metrics():
    with pytest.raises(ValueError):
        fit([(1, 1, 0.9, 0)])
    rows = [
        dict(
            request="1",
            scenario="authorized",
            session="A",
            condition="normal",
            expected_code="A",
            recognized_code="A",
            result="GRANTED",
            pulse="yes",
            pulse_ms="2000",
            latency_ms="120",
        ),
        dict(
            request="2",
            scenario="unknown",
            session="A",
            condition="dim",
            expected_code="UNKNOWN",
            recognized_code="",
            result="TIMEOUT",
            pulse="no",
            pulse_ms="",
            latency_ms="",
        ),
    ]
    report = summarize(rows)
    assert report["by_scenario"]["authorized"]["correct_identity_grants"] == 1
    assert report["latency_p95_ms"] == 120 and report["by_scenario"]["unknown"]["TIMEOUT"] == 1


def test_actual_onnx_cpu(tmp_path):
    from smartdoor.vision import SFACE_FILENAME

    model_dir = data_directory() / "models"
    if not (model_dir / SFACE_FILENAME).exists():
        pytest.skip("Install signed-off OpenCV Zoo models with python -m smartdoor.models")
    frame = np.random.default_rng(74).integers(40, 190, (240, 320, 3), dtype=np.uint8)
    jpeg = cv2.imencode(".jpg", frame)[1].tobytes()
    assert Vision(tmp_path).observe(jpeg).reason == "ai_unavailable"
    vision = Vision(model_dir)
    assert vision.observe(jpeg).reason == "no_face"
    # Exercise the real SFace network on a synthetic ROI, separately from detector accuracy.
    row = np.array([60, 20, 160, 180, 100, 85, 165, 85, 132, 115, 108, 150, 158, 150, 0.99], np.float32)
    vision.detector.landmark_rows = lambda _: [row]
    obs = vision.observe(jpeg)
    assert obs.reason == "face" and len(obs.vector) == 128 * 4
    assert vision.observe(b"invalid").reason == "invalid_jpeg"
    assert PROFILE.startswith("yunet-")
