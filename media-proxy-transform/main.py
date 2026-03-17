"""Media Proxy Transform Service — Misskey-compatible image processing."""

import io
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from PIL import Image

PRESETS = {
    "avatar": (320, 320, "webp"),
    "emoji": (128, 128, "webp"),
    "preview": (200, 200, "webp"),
    "badge": (96, 96, "png"),
}

MAX_INPUT_SIZE = 20 * 1024 * 1024  # 20 MB


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}


def _resolve_params(
    avatar: str | None,
    emoji: str | None,
    preview: str | None,
    badge: str | None,
    static: str | None,
    width: str | None,
    height: str | None,
) -> tuple[int | None, int | None, str, bool]:
    """Resolve parameters to (width, height, format, static)."""
    for key, preset in PRESETS.items():
        param = locals().get(key)
        if param and param == "1":
            return preset[0], preset[1], preset[2], static == "1"

    # Custom size
    w = int(width) if width else None
    h = int(height) if height else None
    if w and w > 4096:
        w = 4096
    if h and h > 4096:
        h = 4096
    return w, h, "webp", static == "1"


def _process_image(
    data: bytes,
    target_w: int | None,
    target_h: int | None,
    fmt: str,
    extract_static: bool,
) -> tuple[bytes, str]:
    """Process image: resize, format convert, static frame extraction."""
    img = Image.open(io.BytesIO(data))

    # Extract first frame for animated images
    if extract_static and hasattr(img, "n_frames") and img.n_frames > 1:
        img.seek(0)
        img = img.copy()

    # Convert mode for WebP/PNG compatibility
    if img.mode == "RGBA" and fmt == "webp":
        pass  # WebP supports RGBA
    elif img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if fmt == "webp" else "RGB")

    # Resize with cover-fit (fill + center crop)
    if target_w and target_h:
        orig_w, orig_h = img.size
        if orig_w > target_w or orig_h > target_h:
            # Scale to cover target dimensions
            scale = max(target_w / orig_w, target_h / orig_h)
            new_w = int(orig_w * scale)
            new_h = int(orig_h * scale)
            img = img.resize((new_w, new_h), Image.LANCZOS)

            # Center crop to target
            left = (new_w - target_w) // 2
            top = (new_h - target_h) // 2
            img = img.crop((left, top, left + target_w, top + target_h))

    # Encode
    buf = io.BytesIO()
    if fmt == "webp":
        img.save(buf, format="WEBP", quality=80)
        content_type = "image/webp"
    else:
        img.save(buf, format="PNG")
        content_type = "image/png"

    return buf.getvalue(), content_type


@app.post("/transform")
async def transform(
    file: UploadFile = File(...),
    avatar: str | None = Form(None),
    emoji: str | None = Form(None),
    preview: str | None = Form(None),
    badge: str | None = Form(None),
    static: str | None = Form(None),
    width: str | None = Form(None),
    height: str | None = Form(None),
):
    data = await file.read()
    if len(data) > MAX_INPUT_SIZE:
        raise HTTPException(status_code=413, detail="Input too large")

    target_w, target_h, fmt, extract_static = _resolve_params(
        avatar, emoji, preview, badge, static, width, height,
    )

    try:
        result, content_type = _process_image(
            data, target_w, target_h, fmt, extract_static,
        )
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid image")

    return Response(
        content=result,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=86400"},
    )
