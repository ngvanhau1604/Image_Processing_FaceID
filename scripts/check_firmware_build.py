"""Compile the enabled firmware paths using disposable synthetic credentials and wiring."""

import argparse
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from smartdoor.hardware import PIN_NAMES, make_tls, prepare_firmware
from smartdoor.setup import provision
from smartdoor.storage import Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli", default="arduino-cli")
    parser.add_argument("--build-path", type=Path)
    args = parser.parse_args()
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        store = Store(root)
        provision(store, "ci", "disposable-build-fixture")
        make_tls(root, "127.0.0.1")
        # Synthetic compile-time configuration, never a wiring recommendation.
        profile = dict(
            sensor="OV3660",
            pinout_source="compile fixture",
            camera=dict(zip(PIN_NAMES, [11, 9, 8, 10, 12, 18, 17, 16, 15, 13, 6, 7, 4, 5, -1, -1])),
            relay=dict(gpio=21, active_high=False),
        )
        sketch = prepare_firmware(
            store, profile, "https://127.0.0.1:8443", "fixture", "fixture", "127.0.0.1", True
        )
        cmd = [args.cli, "compile", "--fqbn", "esp32:esp32:esp32s3:FlashSize=16M,PSRAM=opi"]
        if args.build_path:
            cmd.extend(["--build-path", str(args.build_path)])
        subprocess.run(cmd + [str(sketch)], check=True)


if __name__ == "__main__":
    main()
