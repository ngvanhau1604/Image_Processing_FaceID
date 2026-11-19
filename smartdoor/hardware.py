"""Create LAN TLS credentials and a private, buildable copy of the firmware."""

import argparse
import getpass
import ipaddress
import json
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from .storage import ROOT, Store, data_directory

PIN_NAMES = (
    "d0",
    "d1",
    "d2",
    "d3",
    "d4",
    "d5",
    "d6",
    "d7",
    "xclk",
    "pclk",
    "vsync",
    "href",
    "sda",
    "scl",
    "pwdn",
    "reset",
)


def make_tls(folder, host):
    directory = folder / "tls"
    directory.mkdir(mode=0o700, exist_ok=False)
    now = datetime.now(timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Smart Door LAN CA")])
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)])

    def cert(subject, public):
        return (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(ca_name)
            .public_key(public)
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=365))
        )

    ca = (
        cert(ca_name, ca_key.public_key())
        .add_extension(x509.BasicConstraints(True, 0), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    try:
        endpoint = x509.IPAddress(ipaddress.ip_address(host))
    except ValueError:
        endpoint = x509.DNSName(host)
    server = (
        cert(name, key.public_key())
        .add_extension(x509.BasicConstraints(False, None), True)
        .add_extension(
            x509.SubjectAlternativeName(
                [endpoint, x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            False,
        )
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), False)
        .sign(ca_key, hashes.SHA256())
    )
    for filename, data in (
        ("ca.pem", ca.public_bytes(serialization.Encoding.PEM)),
        ("server.pem", server.public_bytes(serialization.Encoding.PEM)),
        (
            "server.key",
            key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
            ),
        ),
    ):
        with os.fdopen(
            os.open(directory / filename, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "wb"
        ) as out:
            out.write(data)
    print(directory)


def board_pins(profile, relay_enabled):
    if profile.get("sensor") != "OV3660" or not profile.get("pinout_source"):
        raise ValueError("Cần nguồn đối chiếu sơ đồ DVP của đúng board OV3660")
    pins = [profile["camera"][name] for name in PIN_NAMES]
    valid = set(range(0, 22)) | set(range(38, 49))
    if any(
        type(pin) is not int or (pin not in valid and not (pin == -1 and i >= 14))
        for i, pin in enumerate(pins)
    ):
        raise ValueError("Thiếu hoặc sai chân camera")
    used = [p for p in pins if p >= 0]
    if len(set(used)) != len(used):
        raise ValueError("Trùng chân camera")
    relay = profile.get("relay", {})
    pin = relay.get("gpio", -1) if relay_enabled else -1
    if relay_enabled:
        reserved = {0, 2, 3, 19, 20, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 48}
        if (
            type(pin) is not int
            or pin not in valid - set(used) - reserved
            or type(relay.get("active_high")) is not bool
        ):
            raise ValueError("GPIO relay xung đột hoặc chưa xác nhận mức kích")
    return pins, pin, bool(relay.get("active_high"))


def prepare_firmware(store, profile, url, ssid, password, ntp, relay_enabled=False):
    pins, gpio, polarity = board_pins(profile, relay_enabled)
    endpoint = urlsplit(url)
    if (
        endpoint.scheme != "https"
        or not endpoint.hostname
        or endpoint.path not in ("", "/")
        or endpoint.query
        or endpoint.fragment
        or endpoint.username
    ):
        raise ValueError("Cần HTTPS origin của máy chủ")
    cert = (store.folder / "tls" / "ca.pem").read_text()
    with store.transaction(False) as db:
        row = db.execute("SELECT secret FROM devices WHERE id='door-kit' AND simulated=0").fetchone()
    if not row:
        raise ValueError("Chạy smartdoor.setup trước")
    directory = store.folder / "firmware" / "smart_door"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    for name in ("smart_door.ino", "defaults.h"):
        shutil.copyfile(ROOT / "firmware" / "smart_door" / name, directory / name)
    constants = {
        "WIFI_NAME": ssid,
        "WIFI_PASS": password,
        "BASE_URL": url.rstrip("/"),
        "NTP_HOST": ntp,
        "DEVICE_ID": "door-kit",
        "DEVICE_KEY": row[0],
        "TRUST_CA": cert,
    }
    lines = [
        "#pragma once",
        "constexpr bool CAMERA_CONFIGURED = true;",
        "constexpr int CAM_PINS[16] = {" + ",".join(map(str, pins)) + "};",
        f"constexpr int RELAY_PIN = {gpio};",
        f"constexpr bool RELAY_ACTIVE_HIGH = {str(polarity).lower()};",
    ]
    lines.extend(f"constexpr char {k}[] = {json.dumps(v, ensure_ascii=False)};" for k, v in constants.items())
    with os.fdopen(
        os.open(directory / "private_config.h", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600),
        "w",
        encoding="utf8",
    ) as out:
        out.write("\n".join(lines) + "\n")
    return directory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("tls").add_argument("host")
    board = commands.add_parser("prepare")
    board.add_argument("--profile", type=Path, required=True)
    board.add_argument("--url", required=True)
    board.add_argument("--ssid", required=True)
    board.add_argument("--ntp", required=True)
    board.add_argument("--enable-verified-relay", action="store_true")
    args = parser.parse_args()
    folder = data_directory()
    if args.command == "tls":
        make_tls(folder, args.host)
    else:
        print(
            prepare_firmware(
                Store(folder),
                json.loads(args.profile.read_text(encoding="utf8")),
                args.url,
                args.ssid,
                getpass.getpass("Wi-Fi password: "),
                args.ntp,
                args.enable_verified_relay,
            )
        )


if __name__ == "__main__":
    main()
