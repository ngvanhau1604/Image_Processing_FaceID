"""Install hash-pinned OpenCV Zoo models and their original licenses."""

from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.request import urlopen
from ai_pipeline.detection import YUNET_COMMIT, YUNET_FILENAME, YUNET_SHA256
from .storage import data_directory
from .vision import SFACE_FILENAME, SFACE_SHA256


def install(directory):
    directory.mkdir(parents=True, exist_ok=True)
    for project, filename, expected in (
        ("face_detection_yunet", YUNET_FILENAME, YUNET_SHA256),
        ("face_recognition_sface", SFACE_FILENAME, SFACE_SHA256),
    ):
        base = f"opencv/opencv_zoo/{YUNET_COMMIT}/models/{project}/"
        dest = directory / filename
        if not dest.exists() or sha256(dest.read_bytes()).hexdigest() != expected:
            with NamedTemporaryFile(dir=directory, delete=False) as tmp:
                part = Path(tmp.name)
            try:
                with (
                    urlopen(
                        "https://media.githubusercontent.com/media/" + base + filename, timeout=90
                    ) as source,
                    part.open("wb") as output,
                ):
                    digest = sha256()
                    while chunk := source.read(262144):
                        output.write(chunk)
                        digest.update(chunk)
                        if output.tell() > 40_000_000:
                            raise ValueError("Unexpected model length")
                if digest.hexdigest() != expected:
                    raise ValueError(f"Checksum mismatch: {filename}")
                part.replace(dest)
            finally:
                part.unlink(missing_ok=True)
        with urlopen("https://raw.githubusercontent.com/" + base + "LICENSE", timeout=30) as response:
            (directory / (project + "-LICENSE.txt")).write_bytes(response.read(100000))
        print("Verified", filename)


if __name__ == "__main__":
    install(data_directory() / "models")
