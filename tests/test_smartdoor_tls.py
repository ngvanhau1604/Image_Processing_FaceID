import socket
import threading
import time

import pytest
import requests
import uvicorn

from smartdoor.hardware import make_tls
from smartdoor.protocol import VERIFY, Pending, Ticket
from smartdoor.server import create_app
from smartdoor.setup import provision
from smartdoor.storage import Store


def test_physical_device_requires_the_provisioned_server_certificate(tmp_path):
    make_tls(tmp_path, "127.0.0.1")
    store = Store(tmp_path)
    provision(store, "operator", "private-test-account")
    with store.transaction(False) as db:
        key = db.execute("SELECT secret FROM devices WHERE id='door-kit'").fetchone()[0]
    tls = tmp_path / "tls"
    config = uvicorn.Config(
        create_app(tmp_path),
        log_level="warning",
        ssl_certfile=str(tls / "server.pem"),
        ssl_keyfile=str(tls / "server.key"),
    )
    server = uvicorn.Server(config)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started:
                assert time.monotonic() < deadline and thread.is_alive()
                time.sleep(0.02)
            url = f"https://127.0.0.1:{port}{VERIFY}"
            ticket = Ticket.new("door-kit", "a" * 32)
            body = b"not a jpeg"
            headers = ticket.headers(key, VERIFY, body)
            with requests.Session() as session:
                session.trust_env = False
                with pytest.raises(requests.exceptions.SSLError):
                    session.post(url, headers=headers, data=body, timeout=4)
                response = session.post(
                    url, headers=headers, data=body, verify=str(tls / "ca.pem"), timeout=4
                )
            assert response.status_code == 200
            assert Pending(ticket).consume(key, response.text) == ("ERROR", "invalid_jpeg")
            with store.transaction(False) as db:
                assert db.execute("SELECT COUNT(*) FROM events WHERE decision='GRANTED'").fetchone()[0] == 0
        finally:
            server.should_exit = True
            thread.join(10)
