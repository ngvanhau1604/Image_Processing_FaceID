"""Fit camera-specific thresholds and summarize independent, labelled trials."""

import argparse
import csv
import hashlib
import json
import math
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

from .storage import ROOT, Store, audit, data_directory, now_ms
from .vision import PROFILE


def fit(samples):
    known = sum(expected is not None for expected, *_ in samples)
    if not 0 < known < len(samples):
        raise ValueError("Cần lượt độc lập của cả người đã đăng ký và người lạ")
    choices = []
    for threshold in (v / 100 for v in range(20, 96)):
        for margin in (v / 100 for v in range(2, 21, 2)):
            right = wrong = 0
            for expected, candidate, top, second in samples:
                if candidate is not None and top >= threshold and top - second >= margin:
                    right += candidate == expected
                    wrong += candidate != expected
            if right and not wrong:
                choices.append((right, threshold, margin))
    if not choices:
        raise ValueError("Chưa tìm được ngưỡng nhận đúng và không nhận nhầm trong tập hiệu chỉnh")
    return max(choices)


def calibrate(store, device, filename, apply):
    digest = hashlib.sha256(filename.read_bytes()).hexdigest()
    with filename.open(encoding="utf-8-sig", newline="") as stream:
        labels = list(csv.DictReader(stream))
    seen, samples = set(), []
    with store.transaction() as db:
        for label in labels:
            request = label["request"].strip()
            if not request or request in seen or not label["session"].strip():
                raise ValueError("Thiếu mã phiên hoặc mã yêu cầu bị trùng")
            seen.add(request)
            event = db.execute(
                "SELECT * FROM events WHERE device=? AND request=?", (device, request)
            ).fetchone()
            if not event or event["profile"] != PROFILE or event["score"] is None:
                raise ValueError(f"Lượt không có điểm nhận diện hợp lệ: {request}")
            code = label["expected_code"].strip()
            person = (
                None
                if code == "UNKNOWN"
                else db.execute("SELECT id FROM people WHERE code=?", (code,)).fetchone()
            )
            if code != "UNKNOWN" and person is None:
                raise ValueError("Mã người dùng không tồn tại")
            samples.append(
                (person[0] if person else None, event["candidate"], event["score"], event["runner_up"])
            )
        right, threshold, margin = fit(samples)
        report = dict(
            device=device,
            profile=PROFILE,
            threshold=threshold,
            margin=margin,
            samples=len(samples),
            known_correct=right,
            manifest_sha256=digest,
            calibration_sessions=sorted({r["session"] for r in labels}),
            time=now_ms(),
        )
        if apply:
            db.execute(
                "UPDATE devices SET threshold=?,margin=?,profile=?,calibration=? WHERE id=?",
                (threshold, margin, PROFILE, json.dumps(report), device),
            )
            audit(db, "local_operator", "calibrate", device)
    return report


def percentile(values, p):
    return sorted(values)[math.ceil(p * len(values)) - 1] if values else None


def summarize(rows):
    groups = defaultdict(Counter)
    latency, pulses, seen = [], [], set()
    for row in rows:
        request = row["request"].strip()
        if not request or request in seen:
            raise ValueError("Mã lượt thử bị thiếu hoặc trùng")
        seen.add(request)
        group = row["scenario"]
        if group not in {
            "authorized",
            "unknown",
            "revoked",
            "multiple",
            "empty",
            "print",
            "video",
            "fault",
            "cycle",
        }:
            raise ValueError("Sai tên kịch bản")
        result = row["result"]
        if result not in {"GRANTED", "DENIED", "ERROR", "TIMEOUT"} or row["pulse"] not in {
            "yes",
            "no",
            "unobserved",
        }:
            raise ValueError("Sai kết quả hoặc trạng thái quan sát")
        if not all(row[k].strip() for k in ("session", "condition", "expected_code")):
            raise ValueError("Thiếu điều kiện hoặc nhãn thực nghiệm")
        counts = groups[group]
        counts["trials"] += 1
        counts[result] += 1
        counts["pulse_" + row["pulse"]] += 1
        if group == "authorized" and result == "GRANTED" and row["expected_code"] == row["recognized_code"]:
            counts["correct_identity_grants"] += 1
        if result != "TIMEOUT":
            value = float(row["latency_ms"])
            if not math.isfinite(value) or value < 0:
                raise ValueError("Độ trễ không hợp lệ")
            latency.append(value)
        if row["pulse_ms"]:
            width = float(row["pulse_ms"])
            if not math.isfinite(width) or width < 0 or row["pulse"] != "yes":
                raise ValueError("Độ dài xung không hợp lệ")
            pulses.append(width)
            if width >= 5000:
                counts["ly03_pulse_limit_exceeded"] += 1
    for scenario, counts in groups.items():
        trials = counts["trials"]
        for result in ("GRANTED", "DENIED", "ERROR", "TIMEOUT"):
            counts[result.lower() + "_pct"] = round(100 * counts[result] / trials, 2)
        if scenario == "authorized":
            counts["correct_identity_grant_pct"] = round(100 * counts["correct_identity_grants"] / trials, 2)
            counts["wrong_identity_grant_pct"] = round(
                100 * (counts["GRANTED"] - counts["correct_identity_grants"]) / trials, 2
            )
    return dict(
        trials=len(seen),
        by_scenario=groups,
        measured_latency=len(latency),
        latency_p50_ms=percentile(latency, 0.5),
        latency_p95_ms=percentile(latency, 0.95),
        measured_pulses=len(pulses),
        pulse_min_ms=min(pulses, default=None),
        pulse_max_ms=max(pulses, default=None),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="cmd", required=True)
    cal = subs.add_parser("calibrate")
    cal.add_argument("csv", type=Path)
    cal.add_argument("--device", required=True)
    cal.add_argument("--apply", action="store_true")
    test = subs.add_parser("report")
    test.add_argument("csv", type=Path)
    test.add_argument("--camera", required=True)
    test.add_argument("--device", required=True)
    test.add_argument("--evidence", choices=["simulator", "bench"], required=True)
    args = parser.parse_args()
    store = Store(data_directory())
    if args.cmd == "calibrate":
        report = calibrate(store, args.device, args.csv, args.apply)
    else:
        with args.csv.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        if not rows:
            parser.error("Cần có lượt thử")
        with store.transaction(False) as db:
            device = db.execute(
                "SELECT calibration,simulated FROM devices WHERE id=?", (args.device,)
            ).fetchone()
        if not device or bool(device["simulated"]) != (args.evidence == "simulator"):
            parser.error("Loại bằng chứng không khớp thiết bị")
        calibration = json.loads(device["calibration"]) if device["calibration"] else {}
        if set(calibration.get("calibration_sessions", [])) & {r["session"] for r in rows}:
            parser.error("Phiên nghiệm thu trùng phiên hiệu chỉnh")
        report = summarize(rows)
        report.update(
            camera=args.camera,
            device=args.device,
            evidence=args.evidence,
            model=PROFILE,
            calibration=calibration,
            conditions=sorted({r["condition"] for r in rows}),
            sessions=sorted({r["session"] for r in rows}),
            git_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
