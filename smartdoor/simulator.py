"""Webcam device with a simulated relay. Never drives hardware."""
import argparse
import json
import queue
import secrets
import threading
import time
from pathlib import Path

import cv2
import requests

from .protocol import ACK, VERIFY, PULSE, Pending, Ticket
from .storage import data_directory


class Simulator:
    def __init__(self, url, config, ca=True):
        self.url = url.rstrip("/")
        self.device = config["device"]
        self.key = config["secret"]
        self.ca = ca
        self.boot = secrets.token_hex(16)
        self.acks = queue.Queue()
        self.worker = threading.Thread(target=self.deliver_acks, daemon=True)
        self.worker.start()

    def send(self, path, body, ticket):
        headers = ticket.headers(self.key,path,body)
        headers["Content-Type"] = "image/jpeg" if path == VERIFY else "text/plain"
        response = requests.post(self.url+path,headers=headers,data=body,verify=self.ca,timeout=(2,5),allow_redirects=False)
        if response.status_code != 200:
            raise ValueError(f"HTTP {response.status_code}")
        return response.text

    def deliver_acks(self):
        while True:
            body = self.acks.get()
            try:
                if body is None:
                    return
                for attempt in range(3):
                    try:
                        self.send(ACK,body,Ticket.new(self.device,self.boot))
                        break
                    except (ValueError,requests.RequestException) as exc:
                        print("ACK",attempt+1,str(exc))
            finally:
                self.acks.task_done()

    def scan(self, jpeg, started):
        ticket = Ticket.new(self.device,self.boot)
        pending = Pending(ticket)
        decision, reason = pending.consume(self.key,self.send(VERIFY,jpeg,ticket))
        latency = round((time.monotonic()-started)*1000)
        print(f"{ticket.request} {decision} {reason} latency_ms={latency}", flush=True)
        if decision == "GRANTED":
            pulse_start = time.monotonic()
            print("Relay giả lập BẬT", flush=True)
            try:
                self.acks.put(f"{ticket.request}\nstarted\n0".encode())
                time.sleep(PULSE/1000)
            finally:
                elapsed = round((time.monotonic()-pulse_start)*1000)
                print(f"Relay giả lập TẮT ({elapsed} ms)", flush=True)
                self.acks.put(f"{ticket.request}\nstopped\n{elapsed}".encode())
        return decision,reason,latency

    def close(self):
        self.acks.put(None)
        self.worker.join()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url",default="http://127.0.0.1:8000")
    parser.add_argument("--camera",type=int,default=0)
    parser.add_argument("--ca",type=Path)
    args = parser.parse_args()
    from urllib.parse import urlsplit
    target = urlsplit(args.url)
    if target.scheme != "https" and (target.scheme != "http" or target.hostname not in ("localhost","127.0.0.1","::1")):
        parser.error("HTTPS required outside loopback")
    config = json.loads((data_directory() / "simulator.json").read_text())
    client = Simulator(args.url,config,str(args.ca) if args.ca else True)
    camera = cv2.VideoCapture(args.camera)
    try:
        if not camera.isOpened():
            raise RuntimeError("Không mở được webcam. Chọn lại --camera.")
        while True:
            start = time.monotonic()
            ok,frame = camera.read()
            if not ok:
                raise RuntimeError("Mất kết nối webcam")
            ok,encoded = cv2.imencode(".jpg",frame,[cv2.IMWRITE_JPEG_QUALITY,85])
            if ok:
                try:
                    client.scan(encoded.tobytes(),start)
                except (ValueError,requests.RequestException) as exc:
                    print("Relay giả lập TẮT:",exc,flush=True)
            time.sleep(0.6)
    except KeyboardInterrupt:
        pass
    finally:
        camera.release()
        client.close()


if __name__ == "__main__":
    main()
