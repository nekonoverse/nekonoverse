use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

/// Bitcoin base58 alphabet (FEP-521a の base58btc に対応)。`app.utils.crypto._BASE58_ALPHABET` と同一。
const BASE58_ALPHABET: &[u8; 58] = b"123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";

/// FEP-521a Multikey の Ed25519 multicodec プレフィックス (varint: 0xED 0x01)。
const ED25519_MULTICODEC_PREFIX: [u8; 2] = [0xed, 0x01];

/// `app.utils.crypto._base58btc_encode` を移植したもの。
/// base58btc エンコード (Bitcoin alphabet 固定)。leading zero は '1' で表現する。
#[pyfunction]
pub fn base58btc_encode(data: &[u8]) -> String {
    let mut digits: Vec<u8> = Vec::new();
    let mut num: Vec<u8> = data.to_vec();

    while !num.iter().all(|&b| b == 0) {
        let mut remainder: u32 = 0;
        let mut quotient: Vec<u8> = Vec::with_capacity(num.len());
        for &byte in &num {
            let acc = remainder * 256 + byte as u32;
            quotient.push((acc / 58) as u8);
            remainder = acc % 58;
        }
        digits.push(BASE58_ALPHABET[remainder as usize]);
        num = quotient;
    }
    digits.reverse();

    let mut result: Vec<u8> = Vec::new();
    for &byte in data {
        if byte == 0 {
            result.push(BASE58_ALPHABET[0]);
        } else {
            break;
        }
    }
    result.extend(digits);
    // BASE58_ALPHABET は ASCII のみなので UTF-8 変換は常に成功する。
    String::from_utf8(result).expect("base58btc alphabet is ASCII")
}

/// `app.utils.crypto._base58btc_decode` を移植したもの。
/// base58btc デコード。不正な文字は ValueError。
#[pyfunction]
pub fn base58btc_decode(text: &str) -> PyResult<Vec<u8>> {
    let mut num: Vec<u8> = vec![0];
    for ch in text.chars() {
        let idx = match BASE58_ALPHABET.iter().position(|&c| c as char == ch) {
            Some(i) => i as u32,
            None => {
                return Err(PyValueError::new_err(format!(
                    "invalid base58btc character: {ch:?}"
                )));
            }
        };
        let mut carry = idx;
        for byte in num.iter_mut().rev() {
            let acc = (*byte as u32) * 58 + carry;
            *byte = (acc & 0xFF) as u8;
            carry = acc >> 8;
        }
        while carry > 0 {
            num.insert(0, (carry & 0xFF) as u8);
            carry >>= 8;
        }
    }

    // 数値部分を big-endian に (先頭の 0 バイトは捨てる。n == 0 なら空バイト列)
    let body: Vec<u8> = match num.iter().position(|&b| b != 0) {
        Some(i) => num[i..].to_vec(),
        None => Vec::new(),
    };

    // leading '1' を 0x00 byte に戻す
    let leading_zeros = text.chars().take_while(|&c| c == BASE58_ALPHABET[0] as char).count();

    let mut result = vec![0u8; leading_zeros];
    result.extend(body);
    Ok(result)
}

/// `app.utils.crypto.ed25519_multibase_to_public_bytes` を移植したもの。
/// Multikey 形式 (`z6Mk...`) から Ed25519 公開鍵 32 byte を抽出する。
#[pyfunction]
pub fn ed25519_multibase_to_public_bytes(multibase: &str) -> PyResult<Vec<u8>> {
    if !multibase.starts_with('z') {
        return Err(PyValueError::new_err("Multikey must start with 'z' (base58btc)"));
    }
    let decoded = base58btc_decode(&multibase[1..])?;
    if !decoded.starts_with(&ED25519_MULTICODEC_PREFIX) {
        return Err(PyValueError::new_err(
            "Multikey does not have Ed25519 multicodec prefix (0xED 0x01)",
        ));
    }
    let raw = &decoded[ED25519_MULTICODEC_PREFIX.len()..];
    if raw.len() != 32 {
        return Err(PyValueError::new_err(format!(
            "Ed25519 public key must be 32 bytes, got {}",
            raw.len()
        )));
    }
    Ok(raw.to_vec())
}
