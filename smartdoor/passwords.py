"""PBKDF2 format shared with AttendAI's password verifier."""

import hashlib
import hmac
import secrets


def hash_password(password):
    salt = secrets.token_hex(16)
    value = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 600_000)
    return f"pbkdf2_sha256$600000${salt}${value.hex()}"


def verify_password(password, stored):
    algorithm, rounds, salt, value = stored.split("$")
    if algorithm != "pbkdf2_sha256" or int(rounds) != 600_000:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(rounds))
    return hmac.compare_digest(digest.hex(), value)
