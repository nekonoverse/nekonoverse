/// 顔検出のバウンディングボックス。座標系は元画像のピクセル座標。
pub struct BBox {
    pub xmin: f64,
    pub ymin: f64,
    pub xmax: f64,
    pub ymax: f64,
}

/// 1件の顔検出結果。
pub struct Detection {
    pub bbox: BBox,
}

/// `app.utils.focal.focal_from_detections` を移植したもの。
/// 顔検出結果からフォーカルポイントを計算する。
///
/// すべてのバウンディングボックスの和集合を使用し、
/// 複数の顔がある画像では1つだけでなく全検出顔の中心にフォーカルポイントを設定する。
pub fn focal_from_detections(
    detections: &[Detection],
    width: f64,
    height: f64,
) -> Option<(f64, f64)> {
    if detections.is_empty() || width <= 0.0 || height <= 0.0 {
        return None;
    }

    let mut xmin = f64::INFINITY;
    let mut ymin = f64::INFINITY;
    let mut xmax = f64::NEG_INFINITY;
    let mut ymax = f64::NEG_INFINITY;

    for d in detections {
        xmin = xmin.min(d.bbox.xmin);
        ymin = ymin.min(d.bbox.ymin);
        xmax = xmax.max(d.bbox.xmax);
        ymax = ymax.max(d.bbox.ymax);
    }

    let cx = (xmin + xmax) / 2.0;
    // 頭部/髪のクロッピングを防ぐため顔ボックスの上部寄り (上から 1/3) にバイアス
    let cy = ymin + (ymax - ymin) / 3.0;

    let focal_x = ((cx / width) * 2.0 - 1.0).clamp(-1.0, 1.0);
    let focal_y = (1.0 - (cy / height) * 2.0).clamp(-1.0, 1.0);

    Some((focal_x, focal_y))
}
