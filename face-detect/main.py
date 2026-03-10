"""
Standalone face detection microservice (HF Inference API object-detection compatible).

Runs on a separate machine with GPU (e.g., RTX 3050).
Accepts base64-encoded images, returns face bounding boxes.

Detection strategy:
  1. Anime face detection (lbpcascade_animeface, OpenCV) — fast, CPU-only
  2. Real face detection (MTCNN, PyTorch) — fallback if no anime faces found
"""

import base64
import io
from contextlib import asynccontextmanager
from pathlib import Path

import cv2
import numpy as np
import torch
from facenet_pytorch import MTCNN
from fastapi import FastAPI, HTTPException
from PIL import Image
from pydantic import BaseModel, Field

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
mtcnn: MTCNN | None = None
anime_cascade: cv2.CascadeClassifier | None = None

CASCADE_PATH = Path(__file__).parent / "lbpcascade_animeface.xml"


@asynccontextmanager
async def lifespan(app: FastAPI):
    global mtcnn, anime_cascade
    mtcnn = MTCNN(keep_all=True, device=device)
    if CASCADE_PATH.exists():
        anime_cascade = cv2.CascadeClassifier(str(CASCADE_PATH))
        if anime_cascade.empty():
            anime_cascade = None
    yield
    mtcnn = None
    anime_cascade = None


app = FastAPI(title="Face Detection Service", lifespan=lifespan)


class DetectionParameters(BaseModel):
    threshold: float = Field(default=0.5, ge=0.0, le=1.0)


class DetectionRequest(BaseModel):
    inputs: str
    parameters: DetectionParameters = Field(default_factory=DetectionParameters)


class BoundingBox(BaseModel):
    xmin: int
    ymin: int
    xmax: int
    ymax: int


class DetectionResult(BaseModel):
    label: str = "face"
    score: float
    box: BoundingBox


def _decode_image(b64: str) -> Image.Image:
    try:
        image_data = base64.b64decode(b64)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 input")
    try:
        return Image.open(io.BytesIO(image_data)).convert("RGB")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid image data")


def _detect_anime(image: Image.Image, min_score: float) -> list[DetectionResult]:
    """Detect anime faces using OpenCV cascade classifier."""
    if anime_cascade is None:
        return []

    img_array = np.array(image)
    gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
    gray = cv2.equalizeHist(gray)

    # minSize relative to image — skip tiny false positives
    min_dim = min(image.width, image.height)
    min_face = max(24, min_dim // 12)

    faces = anime_cascade.detectMultiScale(
        gray,
        scaleFactor=1.1,
        minNeighbors=5,
        minSize=(min_face, min_face),
    )

    if len(faces) == 0:
        return []

    results: list[DetectionResult] = []
    for x, y, w, h in faces:
        # Cascade doesn't give confidence; use neighbor count heuristic.
        # Score is set to 0.8 as a constant for anime detections.
        score = 0.8
        if score < min_score:
            continue
        results.append(
            DetectionResult(
                label="anime_face",
                score=score,
                box=BoundingBox(xmin=int(x), ymin=int(y), xmax=int(x + w), ymax=int(y + h)),
            )
        )
    return results


def _detect_real(image: Image.Image, min_score: float) -> list[DetectionResult]:
    """Detect real faces using MTCNN."""
    if mtcnn is None:
        return []

    boxes, probs = mtcnn.detect(image)
    if boxes is None or probs is None:
        return []

    results: list[DetectionResult] = []
    for box, prob in zip(boxes, probs):
        if prob is None or prob < min_score:
            continue
        x1, y1, x2, y2 = box
        results.append(
            DetectionResult(
                label="face",
                score=round(float(prob), 4),
                box=BoundingBox(xmin=int(x1), ymin=int(y1), xmax=int(x2), ymax=int(y2)),
            )
        )
    return results


@app.post("/object-detection", response_model=list[DetectionResult])
async def detect_faces(request: DetectionRequest):
    """Detect faces in a base64-encoded image (HF Inference API compatible).

    Strategy: anime face first, then real face fallback.
    """
    image = _decode_image(request.inputs)
    threshold = request.parameters.threshold

    # 1. Try anime face detection first
    results = _detect_anime(image, threshold)

    # 2. Fallback to real face detection
    if not results:
        results = _detect_real(image, threshold)

    results.sort(key=lambda r: r.score, reverse=True)
    return results


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "device": str(device),
        "cuda_available": torch.cuda.is_available(),
        "models": {
            "anime": anime_cascade is not None,
            "real": mtcnn is not None,
        },
    }
