"""Provision local credentials. Never print a device key."""

import argparse
import getpass
import json
import os
import secrets
from .passwords import hash_password
from .storage import Store, audit, data_directory


def provision(store, username, password):
    if not 10 <= len(password) <= 256:
        raise ValueError("Mật khẩu cần 10–256 ký tự")
    with store.transaction() as db:
        if not db.execute("SELECT 1 FROM accounts WHERE username=?", (username,)).fetchone():
            db.execute("INSERT INTO accounts VALUES(?,?)", (username, hash_password(password)))
        for device, simulated in (("webcam-demo", 1), ("door-kit", 0)):
            db.execute(
                "INSERT OR IGNORE INTO devices(id,simulated,secret) VALUES(?,?,?)",
                (device, simulated, secrets.token_hex(32)),
            )
        audit(db, username, "setup", "local")
    # Export only the simulator key here. The hardware provisioning step is separate.
    with store.transaction(False) as db:
        key = db.execute("SELECT secret FROM devices WHERE id='webcam-demo'").fetchone()[0]
    path = store.folder / "simulator.json"
    with os.fdopen(
        os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600), "w", encoding="utf8"
    ) as output:
        json.dump({"device": "webcam-demo", "secret": key}, output)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", default="admin")
    args = parser.parse_args()
    store = Store(data_directory())
    password = getpass.getpass("Mật khẩu quản trị (tối thiểu 10 ký tự): ")
    provision(store, args.username, password)
    print("Đã khởi tạo tại", store.folder)


if __name__ == "__main__":
    main()
