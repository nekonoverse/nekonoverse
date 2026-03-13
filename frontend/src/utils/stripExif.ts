/**
 * Client-side EXIF metadata stripping for uploaded images.
 *
 * Re-encodes JPEG/PNG images via the Canvas API, which naturally removes
 * all EXIF metadata (GPS coordinates, camera info, etc.).
 *
 * Before stripping, reads the EXIF Orientation tag from JPEG files so the
 * image can be drawn with the correct rotation/flip on the canvas.
 *
 * GIF and WebP files are returned as-is since they may be animated.
 */

/** EXIF orientation values and their corresponding canvas transforms. */
interface OrientationTransform {
  rotate: number;   // degrees clockwise
  flipX: boolean;
  flipY: boolean;
  swapDimensions: boolean;
}

const ORIENTATION_TRANSFORMS: Record<number, OrientationTransform> = {
  1: { rotate: 0, flipX: false, flipY: false, swapDimensions: false },
  2: { rotate: 0, flipX: true, flipY: false, swapDimensions: false },
  3: { rotate: 180, flipX: false, flipY: false, swapDimensions: false },
  4: { rotate: 0, flipX: false, flipY: true, swapDimensions: false },
  5: { rotate: 90, flipX: false, flipY: true, swapDimensions: true },
  6: { rotate: 90, flipX: false, flipY: false, swapDimensions: true },
  7: { rotate: 270, flipX: false, flipY: true, swapDimensions: true },
  8: { rotate: 270, flipX: false, flipY: false, swapDimensions: true },
};

/**
 * Read EXIF orientation tag from a JPEG file's binary data.
 *
 * Parses the JPEG APP1 (Exif) marker manually to find the Orientation tag
 * (tag 0x0112). Returns 1 (normal) if no orientation is found or the file
 * is not a valid JPEG with EXIF data.
 */
function readJpegOrientation(buffer: ArrayBuffer): number {
  const view = new DataView(buffer);

  // Check JPEG SOI marker
  if (view.byteLength < 2 || view.getUint16(0) !== 0xFFD8) {
    return 1;
  }

  let offset = 2;

  while (offset < view.byteLength - 4) {
    const marker = view.getUint16(offset);

    // Must be a valid JPEG marker (0xFF??)
    if ((marker & 0xFF00) !== 0xFF00) {
      return 1;
    }

    // SOS marker means we've reached image data — stop searching
    if (marker === 0xFFDA) {
      return 1;
    }

    const segmentLength = view.getUint16(offset + 2);

    // APP1 marker (0xFFE1) — potential EXIF data
    if (marker === 0xFFE1) {
      return parseExifOrientation(view, offset + 4, segmentLength);
    }

    // Skip to next marker
    offset += 2 + segmentLength;
  }

  return 1;
}

/**
 * Parse EXIF data within an APP1 segment to extract the Orientation tag value.
 */
function parseExifOrientation(
  view: DataView,
  segmentStart: number,
  segmentLength: number,
): number {
  // Check "Exif\0\0" header
  if (segmentStart + 6 > view.byteLength) return 1;

  const exifHeader =
    view.getUint8(segmentStart) === 0x45 &&     // E
    view.getUint8(segmentStart + 1) === 0x78 &&  // x
    view.getUint8(segmentStart + 2) === 0x69 &&  // i
    view.getUint8(segmentStart + 3) === 0x66 &&  // f
    view.getUint8(segmentStart + 4) === 0x00 &&
    view.getUint8(segmentStart + 5) === 0x00;

  if (!exifHeader) return 1;

  const tiffStart = segmentStart + 6;
  const segmentEnd = segmentStart + segmentLength;

  if (tiffStart + 8 > view.byteLength) return 1;

  // Determine byte order from TIFF header
  const byteOrder = view.getUint16(tiffStart);
  const littleEndian = byteOrder === 0x4949; // "II" = Intel = little-endian

  // Verify TIFF magic number (42)
  if (view.getUint16(tiffStart + 2, littleEndian) !== 0x002A) return 1;

  // Get offset to first IFD
  const ifdOffset = view.getUint32(tiffStart + 4, littleEndian);
  const ifdStart = tiffStart + ifdOffset;

  if (ifdStart + 2 > segmentEnd || ifdStart + 2 > view.byteLength) return 1;

  // Read number of IFD entries
  const numEntries = view.getUint16(ifdStart, littleEndian);

  // Iterate through IFD entries to find Orientation tag (0x0112)
  for (let i = 0; i < numEntries; i++) {
    const entryOffset = ifdStart + 2 + i * 12;
    if (entryOffset + 12 > segmentEnd || entryOffset + 12 > view.byteLength) {
      break;
    }

    const tag = view.getUint16(entryOffset, littleEndian);

    if (tag === 0x0112) {
      // Orientation tag found — value is a SHORT (2 bytes)
      const orientation = view.getUint16(entryOffset + 8, littleEndian);
      return orientation >= 1 && orientation <= 8 ? orientation : 1;
    }
  }

  return 1;
}

/**
 * Load a File as an HTMLImageElement.
 */
function loadImage(file: File): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    const url = URL.createObjectURL(file);

    img.onload = () => {
      URL.revokeObjectURL(url);
      resolve(img);
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("Failed to load image"));
    };
    img.src = url;
  });
}

/**
 * Re-encode an image file through the Canvas API to strip EXIF metadata.
 * Reads EXIF orientation from JPEG and applies the correct rotation/flip.
 *
 * Returns a new File with the same name and MIME type but without EXIF data.
 *
 * GIF and WebP files are returned unchanged (they may be animated).
 */
export async function stripExifFromFile(file: File): Promise<File> {
  const type = file.type.toLowerCase();

  // Skip GIF and WebP — they may be animated and Canvas would flatten them
  if (type === "image/gif" || type === "image/webp") {
    return file;
  }

  // Only process JPEG and PNG
  if (type !== "image/jpeg" && type !== "image/png") {
    return file;
  }

  // Read orientation from JPEG EXIF data
  let orientation = 1;
  if (type === "image/jpeg") {
    try {
      const buffer = await file.arrayBuffer();
      orientation = readJpegOrientation(buffer);
    } catch {
      // If reading fails, proceed with default orientation
      orientation = 1;
    }
  }

  // Load image onto a canvas
  const img = await loadImage(file);
  const transform = ORIENTATION_TRANSFORMS[orientation] || ORIENTATION_TRANSFORMS[1];

  // Determine canvas dimensions (swap if orientation requires 90/270 rotation)
  const canvasWidth = transform.swapDimensions ? img.naturalHeight : img.naturalWidth;
  const canvasHeight = transform.swapDimensions ? img.naturalWidth : img.naturalHeight;

  const canvas = document.createElement("canvas");
  canvas.width = canvasWidth;
  canvas.height = canvasHeight;

  const ctx = canvas.getContext("2d");
  if (!ctx) {
    // Canvas not supported — return original
    return file;
  }

  // Apply transformations
  ctx.save();

  // Move to center for rotation/flip
  ctx.translate(canvasWidth / 2, canvasHeight / 2);

  // Apply rotation
  if (transform.rotate !== 0) {
    ctx.rotate((transform.rotate * Math.PI) / 180);
  }

  // Apply flips
  ctx.scale(transform.flipX ? -1 : 1, transform.flipY ? -1 : 1);

  // Draw the image centered (use original dimensions since rotation already handled by transform)
  ctx.drawImage(img, -img.naturalWidth / 2, -img.naturalHeight / 2);

  ctx.restore();

  // Convert canvas to blob with appropriate format
  const outputType = type === "image/png" ? "image/png" : "image/jpeg";
  const quality = type === "image/jpeg" ? 0.92 : undefined;

  const blob = await new Promise<Blob>((resolve, reject) => {
    canvas.toBlob(
      (b) => {
        if (b) resolve(b);
        else reject(new Error("Canvas toBlob failed"));
      },
      outputType,
      quality,
    );
  });

  // Create a new File with the same name and type
  return new File([blob], file.name, { type: outputType });
}

/**
 * Process an array of files, stripping EXIF metadata from supported image types.
 * Non-image files and unsupported formats are returned as-is.
 */
export async function stripExifFromFiles(files: File[]): Promise<File[]> {
  return Promise.all(files.map(stripExifFromFile));
}
