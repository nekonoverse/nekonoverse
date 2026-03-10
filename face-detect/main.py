"""
Standalone face detection microservice (HF Inference API object-detection compatible).

Runs on a separate machine with GPU (e.g., RTX 3050 6GB).
Accepts base64-encoded images, returns face bounding boxes.

Detection modes (DETECTION_MODE env var):
  auto  — anime face (YOLO, GPU) first, then real face (MTCNN, GPU) fallback
  anime — anime face only
  real  — real face only

Anime model: deepghs/anime_face_detection face_detect_v0_n (ONNX, ~12MB, GPU)
Real model:  MTCNN (PyTorch, ~200MB VRAM)
Total VRAM:  ~250MB — fits comfortably on RTX 3050 6GB
"""

import base64
import io
import logging
import os
from contextlib import asynccontextmanager

import numpy as np
import onnxruntime as ort
from fastapi import FastAPI, HTTPException
from huggingface_hub import hf_hub_download
from PIL import Image
from pydantic import BaseModel, Field

logger = logging.getLogger("face-detect")

DETECTION_MODE = os.environ.get("DETECTION_MODE", "auto")  # auto | anime | real
ANIME_MODEL_REPO = "deepghs/anime_face_detection"
ANIME_MODEL_DIR = "face_detect_v0_n"

mtcnn = None
anime_session: ort.InferenceSession | None = None
anime_input_size: tuple[int, int] = (640, 640)
anime_threshold_default: float = 0.5

_cuda_available: bool | None = None


def _check_cuda() -> bool:
    """Check CUDA availability via onnxruntime or torch."""
    global _cuda_available
    if _cuda_available is not None:
        return _cuda_available
    # Try onnxruntime providers first (no torch needed)
    available_providers = ort.get_available_providers()
    if "CUDAExecutionProvider" in available_providers:
        _cuda_available = True
        return True
    # Fallback to torch check if torch is available
    try:
        import torch
        _cuda_available = torch.cuda.is_available()
    except ImportError:
        _cuda_available = False
    return _cuda_available


def _load_anime_model() -> ort.InferenceSession | None:
    """Download and load ONNX anime face model with GPU if available."""
    global anime_threshold_default
    try:
        model_path = hf_hub_download(ANIME_MODEL_REPO, f"{ANIME_MODEL_DIR}/model.onnx")
        threshold_path = hf_hub_download(ANIME_MODEL_REPO, f"{ANIME_MODEL_DIR}/threshold.json")

        import json

        with open(threshold_path) as f:
            thresholds = json.load(f)
            anime_threshold_default = thresholds.get("threshold", 0.5)

        providers = []
        if _check_cuda():
            providers.append("CUDAExecutionProvider")
        providers.append("CPUExecutionProvider")

        session = ort.InferenceSession(model_path, providers=providers)
        actual = session.get_providers()
        logger.info("Anime ONNX providers: %s", actual)
        return session
    except Exception:
        logger.warning("Failed to load anime face model", exc_info=True)
        return None


def _load_mtcnn():
    """Load MTCNN model (requires torch + facenet-pytorch)."""
    try:
        import torch
        from facenet_pytorch import MTCNN
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model = MTCNN(keep_all=True, device=device)
        logger.info("MTCNN loaded on %s", device)
        return model
    except ImportError:
        logger.warning("torch/facenet-pytorch not installed; real face detection unavailable")
        return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global mtcnn, anime_session
    if DETECTION_MODE in ("auto", "real"):
        mtcnn = _load_mtcnn()
    if DETECTION_MODE in ("auto", "anime"):
        anime_session = _load_anime_model()
        logger.info("Anime model loaded: %s", anime_session is not None)
    yield
    mtcnn = None
    anime_session = None


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


def _preprocess_yolo(image: Image.Image, input_size: tuple[int, int]) -> np.ndarray:
    """Resize image with letterboxing and normalize for YOLO ONNX input."""
    iw, ih = image.size
    tw, th = input_size

    scale = min(tw / iw, th / ih)
    nw, nh = int(iw * scale), int(ih * scale)
    resized = image.resize((nw, nh), Image.BILINEAR)

    canvas = Image.new("RGB", (tw, th), (114, 114, 114))
    paste_x, paste_y = (tw - nw) // 2, (th - nh) // 2
    canvas.paste(resized, (paste_x, paste_y))

    arr = np.array(canvas, dtype=np.float32) / 255.0
    arr = arr.transpose(2, 0, 1)  # HWC -> CHW
    return np.expand_dims(arr, axis=0)  # NCHW


def _postprocess_yolo(
    output: np.ndarray,
    orig_size: tuple[int, int],
    input_size: tuple[int, int],
    threshold: float,
) -> list[DetectionResult]:
    """Parse YOLO ONNX output (1, 5, N) -> list of detections."""
    # Output shape: (1, 5, num_boxes) where 5 = cx, cy, w, h, conf
    preds = output[0]  # (5, N)
    if preds.shape[0] == 5:
        cx, cy, w, h, conf = preds
    else:
        # Transposed: (N, 5)
        preds = preds.T
        cx, cy, w, h, conf = preds[0], preds[1], preds[2], preds[3], preds[4]

    iw, ih = orig_size
    tw, th = input_size
    scale = min(tw / iw, th / ih)
    pad_x = (tw - iw * scale) / 2
    pad_y = (th - ih * scale) / 2

    results: list[DetectionResult] = []
    for i in range(len(conf)):
        if conf[i] < threshold:
            continue
        # Convert from input coords to original image coords
        x1 = (cx[i] - w[i] / 2 - pad_x) / scale
        y1 = (cy[i] - h[i] / 2 - pad_y) / scale
        x2 = (cx[i] + w[i] / 2 - pad_x) / scale
        y2 = (cy[i] + h[i] / 2 - pad_y) / scale

        x1 = max(0, int(x1))
        y1 = max(0, int(y1))
        x2 = min(iw, int(x2))
        y2 = min(ih, int(y2))

        if x2 <= x1 or y2 <= y1:
            continue

        results.append(
            DetectionResult(
                label="anime_face",
                score=round(float(conf[i]), 4),
                box=BoundingBox(xmin=x1, ymin=y1, xmax=x2, ymax=y2),
            )
        )

    # NMS — remove overlapping boxes
    if len(results) > 1:
        results = _nms(results, iou_threshold=0.5)

    return results


def _nms(detections: list[DetectionResult], iou_threshold: float) -> list[DetectionResult]:
    """Simple greedy NMS."""
    detections.sort(key=lambda d: d.score, reverse=True)
    keep: list[DetectionResult] = []
    for det in detections:
        if any(_iou(det.box, k.box) > iou_threshold for k in keep):
            continue
        keep.append(det)
    return keep


def _iou(a: BoundingBox, b: BoundingBox) -> float:
    xi1 = max(a.xmin, b.xmin)
    yi1 = max(a.ymin, b.ymin)
    xi2 = min(a.xmax, b.xmax)
    yi2 = min(a.ymax, b.ymax)
    inter = max(0, xi2 - xi1) * max(0, yi2 - yi1)
    area_a = (a.xmax - a.xmin) * (a.ymax - a.ymin)
    area_b = (b.xmax - b.xmin) * (b.ymax - b.ymin)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _detect_anime(image: Image.Image, min_score: float) -> list[DetectionResult]:
    """Detect anime faces using YOLO ONNX model (GPU)."""
    if anime_session is None:
        return []

    input_tensor = _preprocess_yolo(image, anime_input_size)
    input_name = anime_session.get_inputs()[0].name
    outputs = anime_session.run(None, {input_name: input_tensor})

    return _postprocess_yolo(outputs[0], image.size, anime_input_size, min_score)


def _detect_real(image: Image.Image, min_score: float) -> list[DetectionResult]:
    """Detect real faces using MTCNN (GPU)."""
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

    Strategy depends on DETECTION_MODE:
      auto  — anime first, real fallback
      anime — anime only
      real  — real only
    """
    image = _decode_image(request.inputs)
    threshold = request.parameters.threshold
    results: list[DetectionResult] = []

    if DETECTION_MODE in ("auto", "anime"):
        results = _detect_anime(image, threshold)

    if not results and DETECTION_MODE in ("auto", "real"):
        results = _detect_real(image, threshold)

    results.sort(key=lambda r: r.score, reverse=True)
    return results


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "cuda_available": _check_cuda(),
        "detection_mode": DETECTION_MODE,
        "models": {
            "anime": anime_session is not None,
            "real": mtcnn is not None,
        },
    }
