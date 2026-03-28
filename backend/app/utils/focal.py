def focal_from_detections(
    results: list[dict], width: int, height: int
) -> tuple[float, float] | None:
    """顔検出結果からフォーカルポイントを計算する。

    すべてのバウンディングボックスの和集合を使用し、
    複数の顔がある画像では1つだけでなく全検出顔の中心にフォーカルポイントを設定する。
    """
    if not results or width <= 0 or height <= 0:
        return None

    xmin = min(r["box"]["xmin"] for r in results)
    ymin = min(r["box"]["ymin"] for r in results)
    xmax = max(r["box"]["xmax"] for r in results)
    ymax = max(r["box"]["ymax"] for r in results)

    cx = (xmin + xmax) / 2
    # 頭部/髪のクロッピングを防ぐため顔ボックスの上部寄り (上から 1/3) にバイアス
    cy = ymin + (ymax - ymin) / 3

    focal_x = max(-1.0, min(1.0, (cx / width) * 2 - 1))
    focal_y = max(-1.0, min(1.0, 1 - (cy / height) * 2))
    return (focal_x, focal_y)
