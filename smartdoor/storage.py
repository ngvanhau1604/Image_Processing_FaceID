"""Local state for one door. All business mutations use a single SQLite transaction."""

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import URL, create_engine, event
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[1]


def data_directory():
    default = Path(os.getenv("LOCALAPPDATA") or Path.home() / ".local" / "share") / "FaceID-SmartDoor"
    from dotenv import dotenv_values

    override = os.getenv("SMARTDOOR_HOME") or dotenv_values(ROOT / ".env").get("SMARTDOOR_HOME")
    folder = Path(override or default).expanduser().resolve()
    forbidden = [
        ROOT,
        *(Path(v).resolve() for k, v in os.environ.items() if k.lower().startswith("onedrive") and v),
    ]
    if any(folder.is_relative_to(base) for base in forbidden) or any(
        p.lower().startswith("onedrive") for p in folder.parts
    ):
        raise ValueError("SMARTDOOR_HOME must be outside Git and OneDrive")
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    return folder


SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (username TEXT PRIMARY KEY, password_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions (digest TEXT PRIMARY KEY, username TEXT NOT NULL REFERENCES accounts, expires INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS people (id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL, consent INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS devices (id TEXT PRIMARY KEY, simulated INTEGER NOT NULL, secret TEXT NOT NULL,
    boot TEXT, last_seen INTEGER, held INTEGER NOT NULL DEFAULT 0, empty_since INTEGER,
    threshold REAL, margin REAL, profile TEXT, calibration TEXT, manual_until INTEGER, manual_actor TEXT);
CREATE TABLE IF NOT EXISTS permissions (person INTEGER NOT NULL REFERENCES people, device TEXT NOT NULL REFERENCES devices,
    PRIMARY KEY(person, device));
CREATE TABLE IF NOT EXISTS templates (id INTEGER PRIMARY KEY, person INTEGER NOT NULL REFERENCES people,
    profile TEXT NOT NULL, vector BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS enrollments (device TEXT PRIMARY KEY REFERENCES devices, person INTEGER NOT NULL UNIQUE REFERENCES people,
    expires INTEGER NOT NULL, target INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS drafts (id INTEGER PRIMARY KEY, device TEXT NOT NULL REFERENCES enrollments(device) ON DELETE CASCADE,
    fingerprint TEXT NOT NULL, profile TEXT NOT NULL, vector BLOB NOT NULL, UNIQUE(device,fingerprint));
CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, device TEXT NOT NULL REFERENCES devices, boot TEXT NOT NULL,
    request TEXT NOT NULL, time INTEGER NOT NULL, person INTEGER REFERENCES people, decision TEXT NOT NULL,
    reason TEXT NOT NULL, actor TEXT, execution TEXT, pulse_ms INTEGER, score REAL, runner_up REAL, UNIQUE(device,request));
CREATE TABLE IF NOT EXISTS receipts (device TEXT NOT NULL, request TEXT NOT NULL, nonce TEXT NOT NULL, time INTEGER NOT NULL,
    PRIMARY KEY(device,request), UNIQUE(device,nonce));
CREATE INDEX IF NOT EXISTS receipt_time ON receipts(time);
CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, time INTEGER NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL, subject TEXT NOT NULL);
"""


class Store:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.engine = create_engine(
            URL.create("sqlite", database=str(self.folder / "smartdoor.db")), poolclass=NullPool
        )

        @event.listens_for(self.engine, "connect")
        def setup(connection, _):
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA secure_delete=ON")
            connection.execute("PRAGMA busy_timeout=8000")

        with self.transaction() as db:
            for statement in SCHEMA.split(";"):
                if statement.strip():
                    db.execute(statement)
            columns = {r[1] for r in db.execute("PRAGMA table_info(events)")}
            for column, kind in (("candidate", "INTEGER"), ("profile", "TEXT")):
                if column not in columns:
                    db.execute(f"ALTER TABLE events ADD COLUMN {column} {kind}")

    @contextmanager
    def transaction(self, write=True):
        connection = self.engine.raw_connection()
        try:
            db = connection.driver_connection
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield db
            db.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()


def now_ms():
    from time import time_ns

    return time_ns() // 1_000_000


def audit(db, actor, action, subject):
    db.execute(
        "INSERT INTO audit(time,actor,action,subject) VALUES(?,?,?,?)",
        (now_ms(), actor, action, str(subject)),
    )
