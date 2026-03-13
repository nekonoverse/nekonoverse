"""Tests for server-side EXIF metadata stripping."""

import io

from PIL import ExifTags, Image
from PIL.TiffImagePlugin import IFDRational

from app.services.drive_service import strip_exif


def _make_jpeg_with_exif(width=100, height=80, orientation=None, gps=True):
    """Create a JPEG image with EXIF metadata.

    Args:
        width: Image width.
        height: Image height.
        orientation: EXIF orientation tag value (1-8), or None.
        gps: Whether to embed fake GPS data.

    Returns:
        JPEG bytes containing EXIF data.
    """
    img = Image.new("RGB", (width, height), color=(255, 0, 0))
    exif = img.getexif()

    # Add some EXIF tags
    exif[ExifTags.Base.Make] = "TestCamera"
    exif[ExifTags.Base.Model] = "TestModel"
    exif[ExifTags.Base.Software] = "TestSoftware"

    if orientation is not None:
        exif[ExifTags.Base.Orientation] = orientation

    if gps:
        # Add GPS IFD with fake coordinates using IFDRational for proper Pillow compat
        gps_ifd = {
            1: "N",  # GPSLatitudeRef
            2: (IFDRational(35, 1), IFDRational(39, 1), IFDRational(31, 1)),  # GPSLatitude
            3: "E",  # GPSLongitudeRef
            4: (IFDRational(139, 1), IFDRational(41, 1), IFDRational(31, 1)),  # GPSLongitude
        }
        exif[ExifTags.Base.GPSInfo] = gps_ifd

    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif.tobytes())
    return buf.getvalue()


def _make_png_with_exif(width=100, height=80):
    """Create a PNG image with EXIF metadata."""
    img = Image.new("RGB", (width, height), color=(0, 255, 0))
    exif = img.getexif()
    exif[ExifTags.Base.Make] = "TestCamera"
    exif[ExifTags.Base.Model] = "TestModel"

    buf = io.BytesIO()
    img.save(buf, format="PNG", exif=exif.tobytes())
    return buf.getvalue()


def _get_exif(data: bytes) -> dict:
    """Extract EXIF data from image bytes. Returns empty dict if no EXIF."""
    img = Image.open(io.BytesIO(data))
    exif = img.getexif()
    return dict(exif)


class TestStripExifJPEG:
    def test_strips_exif_from_jpeg(self):
        original = _make_jpeg_with_exif()
        # Verify the original has EXIF
        assert _get_exif(original), "Test image should have EXIF data"

        result = strip_exif(original, "image/jpeg")

        # Result should have no EXIF
        assert not _get_exif(result), "EXIF data should be stripped"
        # Result should still be a valid JPEG
        img = Image.open(io.BytesIO(result))
        assert img.format == "JPEG"

    def test_strips_gps_data(self):
        original = _make_jpeg_with_exif(gps=True)
        exif_before = _get_exif(original)
        assert ExifTags.Base.GPSInfo in exif_before, "Should have GPS data before stripping"

        result = strip_exif(original, "image/jpeg")
        exif_after = _get_exif(result)
        assert ExifTags.Base.GPSInfo not in exif_after, "GPS data should be stripped"

    def test_strips_camera_info(self):
        original = _make_jpeg_with_exif()
        exif_before = _get_exif(original)
        assert ExifTags.Base.Make in exif_before

        result = strip_exif(original, "image/jpeg")
        exif_after = _get_exif(result)
        assert ExifTags.Base.Make not in exif_after

    def test_preserves_orientation(self):
        """Image with orientation=6 (rotated 90 CW) should be transposed."""
        # Orientation 6 means the image is stored rotated 90 degrees CW.
        # After exif_transpose, a 100x80 image should become 80x100.
        original = _make_jpeg_with_exif(width=100, height=80, orientation=6)
        result = strip_exif(original, "image/jpeg")

        img = Image.open(io.BytesIO(result))
        # After applying orientation=6 (90 CW rotation), width/height swap
        assert img.size == (80, 100)

    def test_jpeg_without_exif_is_still_valid(self):
        """A JPEG without EXIF should pass through without error."""
        img = Image.new("RGB", (10, 10), color=(0, 0, 255))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        original = buf.getvalue()

        result = strip_exif(original, "image/jpeg")
        img_out = Image.open(io.BytesIO(result))
        assert img_out.format == "JPEG"
        assert img_out.size == (10, 10)


class TestStripExifPNG:
    def test_strips_exif_from_png(self):
        original = _make_png_with_exif()
        assert _get_exif(original), "Test PNG should have EXIF data"

        result = strip_exif(original, "image/png")

        assert not _get_exif(result), "EXIF data should be stripped from PNG"
        img = Image.open(io.BytesIO(result))
        assert img.format == "PNG"

    def test_png_dimensions_preserved(self):
        original = _make_png_with_exif(width=200, height=150)
        result = strip_exif(original, "image/png")

        img = Image.open(io.BytesIO(result))
        assert img.size == (200, 150)


class TestStripExifSkippedFormats:
    def test_gif_is_unchanged(self):
        """GIF data should be returned unchanged (may be animated)."""
        gif_data = b"GIF89a fake gif data"
        result = strip_exif(gif_data, "image/gif")
        assert result is gif_data  # Same object, not just equal

    def test_webp_is_unchanged(self):
        """WebP data should be returned unchanged (may be animated)."""
        webp_data = b"RIFF fake webp data"
        result = strip_exif(webp_data, "image/webp")
        assert result is webp_data

    def test_avif_is_unchanged(self):
        """AVIF data should be returned unchanged."""
        avif_data = b"fake avif data"
        result = strip_exif(avif_data, "image/avif")
        assert result is avif_data

    def test_non_image_is_unchanged(self):
        """Non-image MIME types should be returned unchanged."""
        data = b"some text data"
        result = strip_exif(data, "text/plain")
        assert result is data


class TestStripExifErrorHandling:
    def test_corrupt_jpeg_returns_original(self):
        """Corrupt data should fall back to returning original bytes."""
        corrupt = b"\xff\xd8\xff\xe0 this is not a valid jpeg"
        result = strip_exif(corrupt, "image/jpeg")
        assert result == corrupt

    def test_empty_data_returns_original(self):
        """Empty data should fall back to returning original bytes."""
        result = strip_exif(b"", "image/jpeg")
        assert result == b""
