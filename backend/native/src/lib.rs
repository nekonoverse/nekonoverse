use nekonoverse_core::focal::{
    focal_from_detections as core_focal_from_detections, BBox, Detection,
};
use pyo3::prelude::*;
use pyo3::types::PyAny;

mod crypto;
mod emoji;
mod sanitize;

/// `nekonoverse_core::focal::focal_from_detections` の PyO3 ラッパー。
/// `results` (Python の `list[dict]`) を `Detection` へ変換してから core 実装へ委譲する。
#[pyfunction]
fn focal_from_detections(
    results: Vec<Bound<'_, PyAny>>,
    width: f64,
    height: f64,
) -> PyResult<Option<(f64, f64)>> {
    let detections = results
        .iter()
        .map(|r| {
            let bbox = r.get_item("box")?;
            Ok(Detection {
                bbox: BBox {
                    xmin: bbox.get_item("xmin")?.extract()?,
                    ymin: bbox.get_item("ymin")?.extract()?,
                    xmax: bbox.get_item("xmax")?.extract()?,
                    ymax: bbox.get_item("ymax")?.extract()?,
                },
            })
        })
        .collect::<PyResult<Vec<_>>>()?;

    Ok(core_focal_from_detections(&detections, width, height))
}

#[pymodule]
fn nekonoverse_native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(focal_from_detections, m)?)?;
    m.add_function(wrap_pyfunction!(emoji::is_single_emoji, m)?)?;
    m.add_function(wrap_pyfunction!(sanitize::sanitize_html, m)?)?;
    m.add_function(wrap_pyfunction!(crypto::base58btc_encode, m)?)?;
    m.add_function(wrap_pyfunction!(crypto::base58btc_decode, m)?)?;
    m.add_function(wrap_pyfunction!(
        crypto::ed25519_multibase_to_public_bytes,
        m
    )?)?;
    Ok(())
}
