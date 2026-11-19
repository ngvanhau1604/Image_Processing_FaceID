"""Browser → real HTTP API → CPU ONNX → simulated relay; no physical webcam required."""

import json
import socket
import threading
import time

import cv2
import numpy as np
import pytest
import uvicorn
from smartdoor.server import create_app
from smartdoor.setup import provision
from smartdoor.simulator import Simulator
from smartdoor.storage import Store, data_directory
from smartdoor.vision import Vision
from smartdoor_drawings import drawing


def test_three_access_attempts_in_browser(tmp_path, request):
    if not request.config.getoption("--run-door-browser"):
        pytest.skip("Run with --run-door-browser after installing Chromium and both ONNX models")
    from playwright.sync_api import expect, sync_playwright

    store = Store(tmp_path)
    provision(store, "admin", "only-for-test")
    app = create_app(tmp_path)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        client = None
        try:
            deadline = time.monotonic() + 15
            while not server.started:
                assert thread.is_alive() and time.monotonic() < deadline
                time.sleep(0.02)
            app.state.vision = Vision(data_directory() / "models")
            url = f"http://127.0.0.1:{listener.getsockname()[1]}"
            client = Simulator(url, json.loads((tmp_path / "simulator.json").read_text()))
            empty = cv2.imencode(".jpg", np.full((320, 320, 3), 140, np.uint8))[1].tobytes()

            def scan(frame):
                return client.scan(frame, time.monotonic())[:2]

            def leave():
                assert scan(empty) == ("DENIED", "no_face")
                time.sleep(1.1)
                assert scan(empty) == ("DENIED", "no_face")

            with sync_playwright() as runtime:
                browser = runtime.chromium.launch()
                page = browser.new_page()
                errors = []
                page.on("pageerror", lambda err: errors.append(str(err)))
                page.goto(url)
                page.locator("#password").fill("only-for-test")
                page.get_by_role("button", name="Đăng nhập").click()
                page.locator("#code").fill("ART-1")
                page.locator("#name").fill("Mẫu vẽ A")
                page.locator("#consent").check()
                page.get_by_role("button", name="Thêm người dùng").click()
                page.get_by_role("button", name="Cấp quyền", exact=True).click()
                expect(page.locator("#people")).to_contain_text("Được phép")
                page.get_by_role("button", name="Đăng ký khuôn mặt").click()
                page.get_by_role("button", name="Bắt đầu thu mẫu").click()
                expect(page.locator("#progress")).to_contain_text("0/5")
                for i, x in enumerate([-10, -8, -6, -4, -2]):
                    expected = "enrollment_complete" if i == 4 else "sample_collected"
                    assert scan(drawing(0, x)) == ("DENIED", expected)
                leave()
                assert scan(drawing(0, 0)) == ("GRANTED", "authorized")
                client.acks.join()
                assert scan(drawing(0, 0)) == ("DENIED", "wait_until_clear")
                leave()
                assert scan(drawing(1, -1)) == ("DENIED", "unknown")
                page.get_by_role("button", name="Người dùng và quyền").click()
                page.get_by_role("button", name="Thu hồi").click()
                expect(page.locator("#people")).to_contain_text("Chưa cấp")
                assert scan(drawing(0, 0)) == ("DENIED", "permission_denied")
                page.get_by_role("button", name="Lịch sử truy cập").click()
                expect(page.locator("#events")).to_contain_text("Thiết bị báo đã ngắt")
                expect(page.locator("#events")).to_contain_text("Đã nhận diện · chưa có quyền")
                expect(page.locator("#events")).to_contain_text("Không đủ độ tin cậy")
                assert not errors
                browser.close()
        finally:
            if client:
                client.close()
            server.should_exit = True
            thread.join(10)
