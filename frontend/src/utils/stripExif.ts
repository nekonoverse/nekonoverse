/**
 * Client-side EXIF metadata stripping for uploaded images.
 *
 * Re-encodes JPEG/PNG images via the Canvas API, which naturally removes
 * all EXIF metadata (GPS coordinates, camera info, etc.).
 *
 * Modern browsers (iOS Safari 13.1+, Chrome 81+, Firefox 26+) automatically
 * apply EXIF Orientation when loading images into <img> elements, so no
 * manual orientation handling is needed — just re-encode via Canvas.
 *
 * GIF and WebP files are returned as-is since they may be animated.
 */

/**
 * Load a File as an HTMLImageElement.
 * The browser automatically applies EXIF orientation during loading.
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
 *
 * The browser auto-applies EXIF orientation when loading the image, so
 * drawing it onto a canvas produces a correctly oriented image without
 * any EXIF data (including GPS, camera info, and orientation tags).
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

  // Load image — browser auto-applies EXIF orientation
  const img = await loadImage(file);

  const canvas = document.createElement("canvas");
  canvas.width = img.naturalWidth;
  canvas.height = img.naturalHeight;

  const ctx = canvas.getContext("2d");
  if (!ctx) {
    return file;
  }

  // Draw the already-oriented image — Canvas output has no EXIF metadata
  ctx.drawImage(img, 0, 0);

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

  return new File([blob], file.name, { type: outputType });
}

/**
 * Process an array of files, stripping EXIF metadata from supported image types.
 * Non-image files and unsupported formats are returned as-is.
 */
export async function stripExifFromFiles(files: File[]): Promise<File[]> {
  return Promise.all(files.map(stripExifFromFile));
}
