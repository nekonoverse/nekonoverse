"""
Standalone face detection microservice (HF Inference API object-detection compatible).

Runs on a separate machine with GPU (e.g., RTX 3050).
Accepts base64-encoded images, returns face bounding boxes.
"""

import base64
import io
from contextlib import asynccontextmanager

import torch
from facenet_pytorch import MTCNN
from fastapi import FastAPI, HTTPException
from PIL import Image
from pydantic import BaseModel, Field

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
mtcnn: MTCNN | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global mtcnn
    mtcnn = MTCNN(keep_all=True, device=device)
    yield
    mtcnn = None


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


@app.post("/object-detection", response_model=list[DetectionResult])
async def detect_faces(request: DetectionRequest):
    """Detect faces in a base64-encoded image (HF Inference API compatible)."""
    if mtcnn is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    try:
        image_data = base64.b64decode(request.inputs)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 input")

    try:
        image = Image.open(io.BytesIO(image_data)).convert("RGB")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid image data")

    boxes, probs = mtcnn.detect(image)

    if boxes is None or probs is None:
        return []

    threshold = request.parameters.threshold
    results: list[DetectionResult] = []

    for box, prob in zip(boxes, probs):
        if prob is None or prob < threshold:
            continue
        x1, y1, x2, y2 = box
        results.append(
            DetectionResult(
                label="face",
                score=round(float(prob), 4),
                box=BoundingBox(
                    xmin=int(x1), ymin=int(y1), xmax=int(x2), ymax=int(y2),
                ),
            )
        )

    results.sort(key=lambda r: r.score, reverse=True)
    return results


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "device": str(device),
        "cuda_available": torch.cuda.is_available(),
        "model": "mtcnn",
    }
