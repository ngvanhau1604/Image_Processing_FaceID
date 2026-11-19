from hashlib import sha256
from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field
from .admin import change, current_admin, router
from .storage import audit, now_ms
from .vision import PROFILE


class Enrollment(BaseModel):
    device: str
    person: int
    samples: int = Field(default=5, ge=5, le=10)


def expire(db, now):
    db.execute("DELETE FROM enrollments WHERE expires<=?", (now,))


@router.post("/enrollments", status_code=201)
def start(payload: Enrollment, request: Request, actor=Depends(current_admin)):
    with change(request) as db:
        expire(db, now_ms())
        person = db.execute("SELECT consent FROM people WHERE id=?", (payload.person,)).fetchone()
        if not person or not person[0]:
            raise HTTPException(409, "Chưa có sự đồng ý thu mẫu")
        db.execute("INSERT INTO enrollments VALUES(?,?,?,?)", (payload.device,payload.person,now_ms()+180_000,payload.samples))
        db.execute("UPDATE devices SET held=1,empty_since=NULL,manual_until=NULL WHERE id=?", (payload.device,))
        audit(db, actor, "start_enrollment", f"{payload.person}/{payload.device}")
    return {"target": payload.samples}


@router.delete("/enrollments/{device}")
def cancel(device: str, request: Request, actor=Depends(current_admin)):
    with change(request) as db:
        db.execute("DELETE FROM enrollments WHERE device=?", (device,))
        audit(db, actor, "cancel_enrollment", device)
    return {"ok": True}


def collect(db, session, observation, jpeg):
    if observation.vector is None:
        return observation.reason
    device = session["device"]
    result = db.execute("INSERT OR IGNORE INTO drafts(device,fingerprint,profile,vector) VALUES(?,?,?,?)",
                        (device, sha256(jpeg).hexdigest(), PROFILE, observation.vector))
    if not result.rowcount:
        return "duplicate_sample"
    count = db.execute("SELECT COUNT(*) FROM drafts WHERE device=?", (device,)).fetchone()[0]
    if count < session["target"]:
        return "sample_collected"
    db.execute("DELETE FROM templates WHERE person=?", (session["person"],))
    db.execute("INSERT INTO templates(person,profile,vector) SELECT ?,profile,vector FROM drafts WHERE device=?",
               (session["person"], device))
    audit(db, device, "finish_enrollment", session["person"])
    db.execute("DELETE FROM enrollments WHERE device=?", (device,))
    return "enrollment_complete"
