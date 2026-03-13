def focal_from_detections(
    results: list[dict], width: int, height: int
) -> tuple[float, float] | None:
    """Calculate focal point from face detection results.

    Uses the union of all bounding boxes so that multi-face images
    get a focal point centered on all detected faces, not just one.
    """
    if not results or width <= 0 or height <= 0:
        return None

    xmin = min(r["box"]["xmin"] for r in results)
    ymin = min(r["box"]["ymin"] for r in results)
    xmax = max(r["box"]["xmax"] for r in results)
    ymax = max(r["box"]["ymax"] for r in results)

    cx = (xmin + xmax) / 2
    cy = (ymin + ymax) / 2

    focal_x = max(-1.0, min(1.0, (cx / width) * 2 - 1))
    focal_y = max(-1.0, min(1.0, 1 - (cy / height) * 2))
    return (focal_x, focal_y)
