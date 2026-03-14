"""Favicon ICO generation from server icon."""

import io
import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.storage import get_public_url, upload_file

logger = logging.getLogger(__name__)

ICO_SIZES = [(16, 16), (32, 32), (48, 48)]


def generate_ico_bytes(image_data: bytes) -> bytes | None:
    """Convert image data to ICO format with multiple sizes.

    Returns ICO bytes or None on failure.
    """
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


async def generate_favicon_ico(
    db: AsyncSession,
    image_data: bytes,
    mime_type: str,
) -> str | None:
    """Generate favicon.ico from image data and upload to S3.

    Returns the public URL of the favicon, or None on failure.
    """
    ico_data = generate_ico_bytes(image_data)
    if not ico_data:
        return None

    s3_key = f"server/favicon-{uuid.uuid4().hex[:8]}.ico"
    try:
        await upload_file(s3_key, ico_data, "image/x-icon")
        return get_public_url(s3_key)
    except Exception:
        logger.warning("Failed to upload favicon.ico to S3", exc_info=True)
        return None
