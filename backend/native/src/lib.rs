use pyo3::prelude::*;
use pyo3::types::PyAny;

mod emoji;
mod sanitize;

/// Mirrors `app.utils.focal.focal_from_detections` (Python) exactly:
/// union bounding box of all detections, Y biased to the top third of the
/// box (avoids cropping heads/hair when multiple faces are present).
#[pyfunction]
fn focal_from_detections(
    results: Vec<Bound<'_, PyAny>>,
    width: f64,
    height: f64,
) -> PyResult<Option<(f64, f64)>> {
    if results.is_empty() || width <= 0.0 || height <= 0.0 {
        return Ok(None);
    }

    let mut xmin = f64::INFINITY;
    let mut ymin = f64::INFINITY;
    let mut xmax = f64::NEG_INFINITY;
    let mut ymax = f64::NEG_INFINITY;

    for r in &results {
        let bbox = r.get_item("box")?;
        let bx_xmin: f64 = bbox.get_item("xmin")?.extract()?;
        let bx_ymin: f64 = bbox.get_item("ymin")?.extract()?;
        let bx_xmax: f64 = bbox.get_item("xmax")?.extract()?;
        let bx_ymax: f64 = bbox.get_item("ymax")?.extract()?;
        xmin = xmin.min(bx_xmin);
        ymin = ymin.min(bx_ymin);
        xmax = xmax.max(bx_xmax);
        ymax = ymax.max(bx_ymax);
    }

    let cx = (xmin + xmax) / 2.0;
    let cy = ymin + (ymax - ymin) / 3.0;

    let focal_x = ((cx / width) * 2.0 - 1.0).clamp(-1.0, 1.0);
    let focal_y = (1.0 - (cy / height) * 2.0).clamp(-1.0, 1.0);

    Ok(Some((focal_x, focal_y)))
}

#[pymodule]
fn nekonoverse_native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(focal_from_detections, m)?)?;
    m.add_function(wrap_pyfunction!(emoji::is_single_emoji, m)?)?;
    m.add_function(wrap_pyfunction!(sanitize::sanitize_html, m)?)?;
    Ok(())
}
