use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

/// `nekonoverse_core::crypto::base58btc_encode` の PyO3 ラッパー。
#[pyfunction]
pub fn base58btc_encode(data: &[u8]) -> String {
    nekonoverse_core::crypto::base58btc_encode(data)
}

/// `nekonoverse_core::crypto::base58btc_decode` の PyO3 ラッパー。
#[pyfunction]
pub fn base58btc_decode(text: &str) -> PyResult<Vec<u8>> {
    nekonoverse_core::crypto::base58btc_decode(text)
        .map_err(|e| PyValueError::new_err(e.to_string()))
}

/// `nekonoverse_core::crypto::ed25519_multibase_to_public_bytes` の PyO3 ラッパー。
#[pyfunction]
pub fn ed25519_multibase_to_public_bytes(multibase: &str) -> PyResult<Vec<u8>> {
    nekonoverse_core::crypto::ed25519_multibase_to_public_bytes(multibase)
        .map_err(|e| PyValueError::new_err(e.to_string()))
}
