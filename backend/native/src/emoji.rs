use pyo3::prelude::*;

/// `nekonoverse_core::emoji::is_single_emoji` の PyO3 ラッパー。
#[pyfunction]
pub fn is_single_emoji(text: &str) -> bool {
    nekonoverse_core::emoji::is_single_emoji(text)
}
