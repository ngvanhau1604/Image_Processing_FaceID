"""Smart Door v1: UTF-8 lines, no final newline; key material is decoded hex."""
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from time import monotonic

from .storage import now_ms

VERIFY = "/api/v1/access/verify"
ACK = "/api/v1/access/ack"
WINDOW = 6500
PULSE = 2000
HEX = re.compile("[0-9a-f]{32}")
DEVICE = re.compile("[a-z0-9-]{1,40}")


def mac(key, *parts):
    data = "\n".join(str(part) for part in parts).encode("ascii")
    return hmac.new(bytes.fromhex(key), data, hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class Ticket:
    device: str
    boot: str
    request: str
    nonce: str
    sent: int

    @classmethod
    def new(cls, device, boot):
        return cls(device, boot, secrets.token_hex(16), secrets.token_hex(16), now_ms())

    def binding(self):
        return (self.device, self.boot, self.request, self.nonce, self.sent)

    def signature(self, key, path, body):
        return mac(key, "v1", path, *self.binding(), hashlib.sha256(body).hexdigest())

    def headers(self, key, path, body):
        headers = dict(zip(("X-Device","X-Boot","X-Request","X-Nonce","X-Sent"), map(str, self.binding())))
        headers["X-Signature"] = self.signature(key, path, body)
        return headers


def response_text(key, ticket, decision, reason, expires):
    fields = (decision, reason, str(expires), str(PULSE if decision == "GRANTED" else 0))
    return "\n".join((*fields, mac(key, "reply", *ticket.binding(), *fields)))


class Pending:
    def __init__(self, ticket):
        self.ticket = ticket
        self.started = monotonic()
        self.used = False

    def consume(self, key, response):
        if self.used:
            raise ValueError("request already consumed")
        self.used = True
        parts = response.split("\n")
        if len(parts) != 5:
            raise ValueError("invalid reply")
        decision, reason, expires, duration, signature = parts
        expected = mac(key, "reply", *self.ticket.binding(), *parts[:4])
        if not hmac.compare_digest(signature, expected):
            raise ValueError("invalid reply signature")
        if not now_ms() <= int(expires) <= self.ticket.sent + WINDOW or (monotonic()-self.started)*1000 > WINDOW:
            raise ValueError("expired reply")
        if decision not in ("GRANTED","DENIED","ERROR") or duration != str(PULSE if decision == "GRANTED" else 0):
            raise ValueError("invalid decision")
        return decision, reason
