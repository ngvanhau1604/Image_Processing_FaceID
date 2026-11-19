import hashlib
import secrets
import sqlite3
from contextlib import contextmanager

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator

from .passwords import verify_password
from .storage import audit, now_ms

router = APIRouter(prefix="/api/v1")
COOKIE = "door_session"


class Login(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)


class Person(BaseModel):
    code: str = Field(pattern=r"^[A-Za-z0-9_-]{1,40}$")
    name: str = Field(min_length=1, max_length=100)
    consent: bool

    @field_validator("name")
    @classmethod
    def validate_name(cls, value):
        if not value.strip():
            raise ValueError("Tên không được trống")
        return value.strip()


class Right(BaseModel):
    device: str
    allowed: bool


def cookie_digest(request):
    return hashlib.sha256(request.cookies.get(COOKIE, "").encode()).hexdigest()


def current_admin(request: Request):
    with request.app.state.store.transaction(False) as db:
        row = db.execute("SELECT username FROM sessions WHERE digest=? AND expires>?", (cookie_digest(request), now_ms())).fetchone()
    if not row:
        raise HTTPException(401, "Vui lòng đăng nhập")
    return row[0]


@contextmanager
def change(request):
    try:
        with request.app.state.store.transaction() as db:
            yield db
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, "Dữ liệu trùng hoặc đối tượng không còn tồn tại") from exc


@router.post("/login")
def login(payload: Login, request: Request, response: Response):
    with request.app.state.store.transaction(False) as db:
        row = db.execute("SELECT password_hash FROM accounts WHERE username=?", (payload.username,)).fetchone()
    if not row or not verify_password(payload.password, row[0]):
        raise HTTPException(401, "Sai thông tin đăng nhập")
    token = secrets.token_urlsafe(32)
    with change(request) as db:
        db.execute("DELETE FROM sessions WHERE expires<=?", (now_ms(),))
        db.execute("INSERT INTO sessions VALUES(?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), payload.username, now_ms()+28_800_000))
    response.set_cookie(COOKIE, token, httponly=True, samesite="strict", secure=request.url.scheme == "https", max_age=28800)
    return {"username": payload.username}


@router.post("/logout")
def logout(request: Request, response: Response, actor=Depends(current_admin)):
    with change(request) as db:
        db.execute("DELETE FROM sessions WHERE digest=?", (cookie_digest(request),))
    response.delete_cookie(COOKIE)
    return {"ok": True}


@router.get("/people")
def people(request: Request, actor=Depends(current_admin)):
    with request.app.state.store.transaction(False) as db:
        rows = db.execute("""SELECT p.*, (SELECT COUNT(*) FROM templates WHERE person=p.id) AS samples
                             FROM people p ORDER BY name,id""")
        return [dict(r, devices=[v[0] for v in db.execute("SELECT device FROM permissions WHERE person=?", (r["id"],))]) for r in rows]


@router.post("/people", status_code=201)
def create_person(payload: Person, request: Request, actor=Depends(current_admin)):
    with change(request) as db:
        person = db.execute("INSERT INTO people(code,name,consent) VALUES(?,?,?)", (payload.code, payload.name, payload.consent)).lastrowid
        audit(db, actor, "create_person", person)
    return {"id": person}


@router.put("/people/{person}")
def update_person(person: int, payload: Person, request: Request, actor=Depends(current_admin)):
    with change(request) as db:
        if not db.execute("UPDATE people SET code=?,name=?,consent=? WHERE id=?", (payload.code,payload.name,payload.consent,person)).rowcount:
            raise HTTPException(404, "Không tìm thấy người dùng")
        if not payload.consent:
            for table in ("permissions", "templates", "enrollments"):
                db.execute(f"DELETE FROM {table} WHERE person=?", (person,))
        audit(db, actor, "update_person" if payload.consent else "withdraw_consent", person)
    return {"id": person}


@router.put("/people/{person}/permission")
def permission(person: int, payload: Right, request: Request, actor=Depends(current_admin)):
    with change(request) as db:
        row = db.execute("SELECT consent FROM people WHERE id=?", (person,)).fetchone()
        if not row or not db.execute("SELECT 1 FROM devices WHERE id=?", (payload.device,)).fetchone():
            raise HTTPException(404, "Không tìm thấy người dùng hoặc thiết bị")
        if payload.allowed and not row[0]:
            raise HTTPException(409, "Cần sự đồng ý trước khi cấp quyền")
        if payload.allowed:
            db.execute("INSERT OR IGNORE INTO permissions VALUES(?,?)", (person,payload.device))
        else:
            db.execute("DELETE FROM permissions WHERE person=? AND device=?", (person,payload.device))
        audit(db, actor, "grant" if payload.allowed else "revoke", f"{person}/{payload.device}")
    return {"allowed": payload.allowed}
