"""FaceID door experiment; never treat it as a production access controller.

No liveness/PAD: photographs or videos may spoof recognition. Default OFF.
"""
from __future__ import annotations

import json
import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.database import get_db
from backend.app.models import ConsentStatus, DoorAccessEvent, FaceTemplate, Student
from backend.app.services.face_templates import build_default_recognizer
from iot_door.protocol import (
    ConfirmationGate, ReplayWindow, response_signature, valid_capture_signature,
)

router = APIRouter(prefix="/iot/door", tags=["experimental-iot-door"])
_replay = ReplayWindow()
_gate = ConfirmationGate()
_log = logging.getLogger(__name__)
_MAX_FRAME = 250_000
_FIVE_POSES = frozenset({"front", "left", "right", "up", "down"})


def _allowed_ids(raw: str) -> set[int]:
    try:
        values = {int(part.strip()) for part in raw.split(",") if part.strip()}
        return values if all(x > 0 for x in values) else set()
    except ValueError:
        return set()


def _identify(db: Session, jpeg: bytes, allowed: set[int]) -> tuple[int | None, str]:
    try:
        import numpy as np
        from ai_pipeline.recognition import match_embedding
        recognizer = build_default_recognizer()
        if recognizer.distance_metric != "euclidean":
            return None, "engine_unavailable"
        frame = recognizer.extract_frame_embeddings(jpeg, max_faces=2)
        if len(frame.faces) != 1 or not frame.faces[0].accepted:
            return None, "face_count_or_quality"
        probe = frame.faces[0].embedding
        if probe.shape != (128,) or not np.isfinite(probe).all():
            return None, "bad_embedding"

        rows = db.scalars(
            select(FaceTemplate)
            .join(Student, Student.id == FaceTemplate.student_id)
            .where(
                FaceTemplate.student_id.in_(allowed),
                Student.deleted_at.is_(None),
                Student.consent_status == ConsentStatus.GRANTED.value,
                FaceTemplate.is_active.is_(True),
                FaceTemplate.model_version == recognizer.model_version,
                FaceTemplate.pose_label.in_(_FIVE_POSES),
            )
        ).all()
        poses: dict[int, set[str]] = {}
        vectors: dict[int, list] = {}
        for item in rows:
            if item.embedding_dim != 128 or len(item.embedding) != 512:
                continue
            vector = np.frombuffer(item.embedding, dtype=np.float32)
            if not np.isfinite(vector).all():
                continue
            poses.setdefault(item.student_id, set()).add(item.pose_label)
            vectors.setdefault(item.student_id, []).append(vector)
        eligible = {person: vectors[person] for person, labels in poses.items()
                    if len(labels) == 5}
        if not eligible:
            return None, "no_authorized_templates"
        settings = get_settings()
        match = match_embedding(
            probe, eligible, threshold=settings.face_distance_threshold,
            margin=settings.face_distance_margin, metric="euclidean",
        )
        return (match.student_id, "recognized") if match.student_id is not None else (None, "no_match")
    except (ImportError, RuntimeError, ValueError, TypeError) as exc:
        _log.warning("Door face engine error: %s", type(exc).__name__)
        return None, "engine_unavailable"


def _reply(secret: str, nonce: str, decision: str, reason: str,
           unlock_ms: int = 0) -> Response:
    payload = {
        "decision": decision, "reason": reason, "request_nonce": nonce,
        "unlock_ms": unlock_ms if decision == "unlock" else 0,
        "valid_until": int(time.time()) + 5,
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return Response(content=raw, media_type="application/json",
                    headers={"X-Door-Response-Signature": response_signature(secret, raw),
                             "Cache-Control": "no-store"})


@router.post("/capture")
async def capture(request: Request, db: Session = Depends(get_db)) -> Response:
    settings = get_settings()
    secret = settings.iot_door_hmac_secret
    allowed = _allowed_ids(settings.iot_door_allowed_student_ids)
    if not settings.iot_door_enabled or len(secret) < 32 or not allowed:
        raise HTTPException(503, "IoT door disabled or not configured")
    device_id = request.headers.get("X-Device-ID", "")
    timestamp = request.headers.get("X-Timestamp", "")
    nonce = request.headers.get("X-Nonce", "")
    signature = request.headers.get("X-Signature", "")
    if device_id != settings.iot_door_device_id:
        raise HTTPException(401, "Unknown device")
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "image/jpeg":
        raise HTTPException(415, "JPEG required")

    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > _MAX_FRAME:
            raise HTTPException(413, "JPEG too large")
        chunks.append(chunk)
    jpeg = b"".join(chunks)
    if len(jpeg) < 4 or not jpeg.startswith(b"\xff\xd8") or not jpeg.endswith(b"\xff\xd9"):
        raise HTTPException(400, "Invalid JPEG")
    if not valid_capture_signature(secret, device_id, timestamp, nonce, jpeg, signature):
        raise HTTPException(401, "Invalid or expired signature")
    if not _replay.claim(device_id, nonce):
        raise HTTPException(409, "Replay rejected")

    person, reason = _identify(db, jpeg, allowed)
    if person is None:
        _gate.reset(device_id)
        decision = "denied"
    else:
        decision = _gate.observe(device_id, person, jpeg,
                                 minimum_hits=settings.iot_door_min_hits)
        reason = "confirmed" if decision == "unlock" else decision
    try:
        db.add(DoorAccessEvent(device_id=device_id, subject_id=person,
                               decision=decision, reason=reason))
        db.commit()
    except Exception:
        db.rollback()
        _log.exception("Audit unavailable; door remains closed")
        return _reply(secret, nonce, "denied", "audit_unavailable")
    _log.info("IoT door decision=%s device=%s subject=%s", decision, device_id, person)
    return _reply(secret, nonce, decision, reason,
                  settings.iot_door_unlock_ms if decision == "unlock" else 0)
