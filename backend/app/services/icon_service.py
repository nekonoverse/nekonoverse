"""Server icon generation: favicon.ico, PWA PNGs."""

import importlib.resources
import io
import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.server_settings_service import get_setting, set_setting
from app.storage import get_public_url, upload_file

logger = logging.getLogger(__name__)

ICO_SIZES = [(16, 16), (32, 32), (48, 48)]


def _load_default_icon() -> bytes:
    """Load the bundled default 512x512 PNG icon."""
    ref = importlib.resources.files("app.assets").joinpath("default-icon-512.png")
    return ref.read_bytes()


def _resize_png(image_data: bytes, size: int) -> bytes:
    """Resize image to square PNG of given size."""
    from PIL import Image

    img = Image.open(io.BytesIO(image_data))
    img = img.convert("RGBA")
    img = img.resize((size, size), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def generate_ico_bytes(image_data: bytes) -> bytes | None:
    """Convert image data to ICO format with multiple sizes."""
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(image_data))
        img = img.convert("RGBA")
        buf = io.BytesIO()
        img.save(buf, format="ICO", sizes=ICO_SIZES)
        return buf.getvalue()
    except Exception:
        logger.warning("Failed to generate favicon.ico", exc_info=True)
        return None


async def generate_all_icons(
    db: AsyncSession,
    image_data: bytes,
    *,
    set_server_icon: bool = True,
) -> dict[str, str]:
    """Generate all icon variants and save URLs to settings.

    Generates: 512 PNG, 192 PNG, favicon.ico.
    Returns dict of setting_key -> url.
    """
    suffix = uuid.uuid4().hex[:8]
    urls: dict[str, str] = {}

    # 512x512 PNG (also used as server icon)
    png_512 = _resize_png(image_data, 512)
    key_512 = f"server/icon-512-{suffix}.png"
    await upload_file(key_512, png_512, "image/png")
    url_512 = get_public_url(key_512)
    urls["pwa_icon_512_url"] = url_512
    await set_setting(db, "pwa_icon_512_url", url_512)

    if set_server_icon:
        urls["server_icon_url"] = url_512
        await set_setting(db, "server_icon_url", url_512)

    # 192x192 PNG
    png_192 = _resize_png(image_data, 192)
    key_192 = f"server/icon-192-{suffix}.png"
    await upload_file(key_192, png_192, "image/png")
    url_192 = get_public_url(key_192)
    urls["pwa_icon_192_url"] = url_192
    await set_setting(db, "pwa_icon_192_url", url_192)

    # favicon.ico
    ico_data = generate_ico_bytes(image_data)
    if ico_data:
        key_ico = f"server/favicon-{suffix}.ico"
        await upload_file(key_ico, ico_data, "image/x-icon")
        url_ico = get_public_url(key_ico)
        urls["favicon_ico_url"] = url_ico
        await set_setting(db, "favicon_ico_url", url_ico)

    await db.commit()
    return urls


async def ensure_default_icons(db: AsyncSession) -> None:
    """Set up default icons if server_icon_url is not configured."""
    existing = await get_setting(db, "server_icon_url")
    if existing:
        return

    logger.info("No server icon configured — generating defaults")
    try:
        default_png = _load_default_icon()
        urls = await generate_all_icons(db, default_png, set_server_icon=True)
        logger.info("Default icons generated: %s", list(urls.keys()))
    except Exception:
        logger.warning("Failed to generate default icons", exc_info=True)
