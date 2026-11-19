import hmac
import sqlite3
from dataclasses import dataclass
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from .admin import change, current_admin
from .enrollment import collect, expire
from .protocol import VERIFY, DEVICE, HEX, WINDOW, Ticket, response_text
from .storage import audit, now_ms
from .vision import MAX_BYTES, PROFILE, identify

router = APIRouter(prefix="/api/v1")


@dataclass
class Decision:
    status: str
    reason: str
    person: int | None = None
    actor: str | None = None
    score: float | None = None
    runner_up: float | None = None
    candidate: int | None = None


async def bounded_body(request: Request):
    limit = MAX_BYTES if request.url.path == VERIFY else 160
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > limit:
            raise HTTPException(413, "Nội dung vượt giới hạn")
        data.extend(chunk)
    return bytes(data)


def authenticate(request, db, body):
    headers = request.headers
    try:
        ticket = Ticket(
            headers["x-device"],
            headers["x-boot"],
            headers["x-request"],
            headers["x-nonce"],
            int(headers["x-sent"]),
        )
        signature = headers["x-signature"]
    except (KeyError, ValueError):
        raise HTTPException(401, "Invalid device headers")
    if not DEVICE.fullmatch(ticket.device) or not all(
        HEX.fullmatch(v) for v in (ticket.boot, ticket.request, ticket.nonce)
    ):
        raise HTTPException(401, "Invalid identifiers")
    device = db.execute("SELECT * FROM devices WHERE id=?", (ticket.device,)).fetchone()
    if not device or (not device["simulated"] and request.url.scheme != "https"):
        raise HTTPException(401, "Invalid device or transport")
    if len(signature) != 64 or not signature.isascii():
        raise HTTPException(401, "Invalid signature")
    if not hmac.compare_digest(ticket.signature(device["secret"], request.url.path, body), signature):
        raise HTTPException(401, "Invalid signature")
    now = now_ms()
    if not now - WINDOW <= ticket.sent <= now + 1000:
        raise HTTPException(401, "Expired request")
    db.execute("DELETE FROM receipts WHERE time<?", (now - 60_000,))
    try:
        db.execute("INSERT INTO receipts VALUES(?,?,?,?)", (ticket.device, ticket.request, ticket.nonce, now))
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Duplicate request")
    if (
        request.url.path == VERIFY
        and db.execute(
            "SELECT 1 FROM events WHERE device=? AND request=?", (ticket.device, ticket.request)
        ).fetchone()
    ):
        raise HTTPException(409, "Duplicate access attempt")
    return device, ticket


def evaluate(db, device, ticket, vision, body):
    now = now_ms()
    name = device["id"]
    if device["boot"] != ticket.boot:
        db.execute("UPDATE devices SET manual_until=NULL, empty_since=NULL WHERE id=?", (name,))
    db.execute("UPDATE devices SET last_seen=?,boot=? WHERE id=?", (now, ticket.boot, name))
    expire(db, now)
    session = db.execute("SELECT * FROM enrollments WHERE device=?", (name,)).fetchone()
    obs = vision.observe(body)
    if obs.reason != "no_face":
        db.execute("UPDATE devices SET empty_since=NULL WHERE id=?", (name,))
    if obs.reason == "ai_unavailable":
        return Decision("ERROR", obs.reason)
    if session:
        return Decision("DENIED", collect(db, session, obs, body), session["person"])
    if obs.reason == "invalid_jpeg":
        return Decision("ERROR", obs.reason)
    if device["manual_until"] and device["manual_until"] >= now and device["boot"] == ticket.boot:
        db.execute("UPDATE devices SET manual_until=NULL WHERE id=?", (name,))
        return Decision("GRANTED", "manual", actor=device["manual_actor"])
    if obs.reason == "no_face":
        if device["held"]:
            start = device["empty_since"] if device["boot"] == ticket.boot else None
            # A long offline interval cannot count as continued absence.
            if start is None or now - (device["last_seen"] or 0) > 3500:
                db.execute("UPDATE devices SET empty_since=? WHERE id=?", (now, name))
            elif now - start >= 1000:
                db.execute("UPDATE devices SET held=0,empty_since=NULL WHERE id=?", (name,))
        return Decision("DENIED", "no_face")
    if obs.vector is None:
        return Decision("DENIED", obs.reason)
    if device["held"]:
        return Decision("DENIED", "wait_until_clear")
    calibrated = device["profile"] == PROFILE and device["threshold"] is not None
    rank = identify(db, obs.vector, -1, 0)
    scores = dict(score=rank.score, runner_up=rank.second_score, candidate=rank.student_id)
    if not device["simulated"] and not calibrated:
        return Decision("DENIED", "calibration_required", **scores)
    threshold, margin = (device["threshold"], device["margin"]) if calibrated else (0.45, 0.06)
    if rank.student_id is None or rank.score < threshold or rank.score - rank.second_score < margin:
        return Decision("DENIED", "unknown", **scores)
    allowed = db.execute(
        "SELECT 1 FROM permissions WHERE device=? AND person=?", (name, rank.student_id)
    ).fetchone()
    return Decision(
        "GRANTED" if allowed else "DENIED",
        "authorized" if allowed else "permission_denied",
        rank.student_id,
        **scores,
    )


@router.post("/access/verify", response_class=PlainTextResponse)
def verify(request: Request, body: bytes = Depends(bounded_body)):
    with request.app.state.store.transaction() as db:
        device, ticket = authenticate(request, db, body)
        result = evaluate(db, device, ticket, request.app.state.vision, body)
        expires = min(ticket.sent + WINDOW, now_ms() + 2500)
        if now_ms() >= expires:
            result = Decision("ERROR", "processing_timeout")
        if result.status == "GRANTED":
            db.execute("UPDATE devices SET held=1,empty_since=NULL WHERE id=?", (ticket.device,))
        db.execute(
            """INSERT INTO events(device,boot,request,time,person,decision,reason,actor,score,runner_up,execution,candidate,profile)
                      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                ticket.device,
                ticket.boot,
                ticket.request,
                now_ms(),
                result.person,
                result.status,
                result.reason,
                result.actor,
                result.score,
                result.runner_up,
                "pending" if result.status == "GRANTED" else None,
                result.candidate,
                PROFILE,
            ),
        )
        reply = response_text(device["secret"], ticket, result.status, result.reason, expires)
    return reply


@router.post("/access/ack")
def ack(request: Request, body: bytes = Depends(bounded_body)):
    with request.app.state.store.transaction() as db:
        _, ticket = authenticate(request, db, body)
        try:
            target, state, ms = body.decode("ascii").split("\n")
            elapsed = int(ms)
            if not HEX.fullmatch(target) or state not in ("started", "stopped") or not 0 <= elapsed <= 60_000:
                raise ValueError()
        except (ValueError, UnicodeError):
            raise HTTPException(422, "Invalid acknowledgement")
        row = db.execute(
            "SELECT id,execution FROM events WHERE device=? AND boot=? AND request=? AND decision='GRANTED'",
            (ticket.device, ticket.boot, target),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Unknown grant")
        if row["execution"] != "stopped":
            db.execute(
                "UPDATE events SET execution=?,pulse_ms=? WHERE id=?",
                (state, elapsed if state == "stopped" else None, row["id"]),
            )
    return {"ok": True}


class DeviceChoice(BaseModel):
    device: str


@router.post("/access/manual-unlock")
def manual(payload: DeviceChoice, request: Request, actor=Depends(current_admin)):
    with change(request) as db:
        now = now_ms()
        expire(db, now)
        row = db.execute("SELECT * FROM devices WHERE id=?", (payload.device,)).fetchone()
        if not row or not row["last_seen"] or now - row["last_seen"] > 10_000:
            raise HTTPException(409, "Thiết bị chưa kết nối")
        if db.execute("SELECT 1 FROM enrollments WHERE device=?", (payload.device,)).fetchone():
            raise HTTPException(409, "Thiết bị đang thu mẫu")
        if (row["manual_until"] or 0) >= now or db.execute(
            "SELECT 1 FROM events WHERE device=? AND decision='GRANTED' AND time>?",
            (payload.device, now - 5000),
        ).fetchone():
            raise HTTPException(409, "Đã có lệnh mở gần đây")
        db.execute(
            "UPDATE devices SET manual_until=?,manual_actor=? WHERE id=?", (now + 5000, actor, payload.device)
        )
        audit(db, actor, "manual_request", payload.device)
    return {"queued": True}


@router.get("/devices/health")
def health(request: Request, actor=Depends(current_admin)):
    with request.app.state.store.transaction(False) as db:
        rows = db.execute(
            """SELECT d.id,simulated,last_seen,profile,e.person,e.target,
            (SELECT COUNT(*) FROM drafts WHERE device=e.device) AS collected FROM devices d
            LEFT JOIN enrollments e ON e.device=d.id AND e.expires>? ORDER BY simulated DESC""",
            (now_ms(),),
        )
        return [dict(r, online=now_ms() - (r["last_seen"] or 0) < 10_000) for r in rows]


@router.get("/access/events")
def events(request: Request, actor=Depends(current_admin)):
    with request.app.state.store.transaction(False) as db:
        return [
            dict(r)
            for r in db.execute("""SELECT e.*, p.name FROM events e LEFT JOIN people p ON p.id=e.person
                                               ORDER BY e.id DESC LIMIT 100""")
        ]
