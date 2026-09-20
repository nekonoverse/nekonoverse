use pyo3::prelude::*;

/// `nekonoverse_core::sanitize::sanitize_html` の PyO3 ラッパー。
#[pyfunction]
pub fn sanitize_html(html: &str) -> String {
    nekonoverse_core::sanitize::sanitize_html(html)
}
