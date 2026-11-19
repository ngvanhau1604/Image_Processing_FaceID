"""One YuNet detection and one aligned SFace descriptor on the original frame."""
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from threading import Lock

import cv2
import numpy as np
from PIL import Image, UnidentifiedImageError

from ai_pipeline.detection import FaceDetectionOptions, HybridFaceDetector, YUNET_FILENAME, YUNET_SHA256
from ai_pipeline.gallery import CompiledGallery
from ai_pipeline.quality import assess_face_quality_v2

SFACE_FILENAME = "face_recognition_sface_2021dec.onnx"
SFACE_SHA256 = "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79"
PROFILE = f"yunet-{YUNET_SHA256[:12]}_sface-{SFACE_SHA256[:12]}_aligned-v1"
MAX_BYTES = 1_000_000


@dataclass(frozen=True)
class Observation:
    reason: str
    vector: bytes | None = None


class Vision:
    def __init__(self, directory):
        self.directory = directory
        self.lock = Lock()
        self.detector = None
        self.recognizer = None

    def load(self):
        detector = HybridFaceDetector(FaceDetectionOptions(backend="yunet", model_path=self.directory / YUNET_FILENAME))
        path = self.directory / SFACE_FILENAME
        if not detector.status()["yunet_ready"] or sha256(path.read_bytes()).hexdigest() != SFACE_SHA256:
            raise ValueError("unverified models")
        self.recognizer = cv2.FaceRecognizerSF.create(str(path), "", cv2.dnn.DNN_BACKEND_OPENCV, cv2.dnn.DNN_TARGET_CPU)
        self.detector = detector

    def observe(self, jpeg):
        try:
            with Image.open(BytesIO(jpeg)) as header:
                if header.format != "JPEG" or max(header.size) > 2048 or min(header.size) < 32:
                    return Observation("invalid_jpeg")
            frame = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION)
            if frame is None:
                return Observation("invalid_jpeg")
        except (ValueError, OSError, UnidentifiedImageError, Image.DecompressionBombError, cv2.error):
            return Observation("invalid_jpeg")
        with self.lock:
            try:
                if self.detector is None:
                    self.load()
                faces = self.detector.landmark_rows(frame)
                if len(faces) != 1:
                    return Observation("no_face" if len(faces) == 0 else "multiple_faces")
                row = faces[0]
                x, y, w, h = row[:4]
                crop = frame[max(0, int(y)):max(0, int(np.ceil(y+h))), max(0, int(x)):max(0, int(np.ceil(x+w)))]
                quality = assess_face_quality_v2(crop)
                if not quality.accepted:
                    reason = (quality.reason or "").lower()
                    label = next((s for s in ("small", "dark", "overexposed", "blurry") if s in reason), "low_detail")
                    return Observation(label)
                aligned = self.recognizer.alignCrop(frame, row)
                vector = self.recognizer.feature(aligned).ravel().astype("<f4")
                if vector.shape != (128,) or not np.isfinite(vector).all() or np.linalg.norm(vector) < 1e-8:
                    return Observation("ai_unavailable")
                return Observation("face", vector.tobytes())
            except (ValueError, OSError, cv2.error):
                return Observation("ai_unavailable")


def identify(db, vector, threshold, margin):
    gallery = {}
    for row in db.execute("""SELECT t.person,t.vector FROM templates t JOIN people p ON t.person=p.id
                             WHERE p.consent=1 AND t.profile=?""", (PROFILE,)):
        gallery.setdefault(row[0], []).append(np.frombuffer(row[1], dtype="<f4"))
    compiled = CompiledGallery(gallery, 128, metric="cosine")
    return compiled.match_many([np.frombuffer(vector, dtype="<f4")], threshold=threshold, margin=margin)[0]
