//! `app/utils/media_proxy.py` の HMAC 署名検証部分を移植したもの。
//! (`media_proxy_url` によるプロキシ URL 生成側は Python にまだ残っている
//! ルート — `statuses.py`/`accounts.py` 等 — からのみ呼ばれるため、
//! こちらでは検証 (`verify`) のみを実装する。`sign` はテスト用。)

use hmac::{Hmac, Mac};
use sha2::Sha256;

use crate::config::Config;

type HmacSha256 = Hmac<Sha256>;

fn to_hex(bytes: &[u8]) -> String {
    use std::fmt::Write;
    let mut s = String::with_capacity(bytes.len() * 2);
    for b in bytes {
        write!(s, "{b:02x}").expect("writing to String cannot fail");
    }
    s
}

/// `app.utils.media_proxy._media_proxy_signing_key` を移植したもの。
/// `media_proxy_key` が空でなければそれを鍵バイト列とし、未設定なら
/// `secret_key` から HMAC-SHA256(secret_key, "media-proxy") で導出した
/// 64桁16進文字列の ASCII バイト列を鍵として使う二段構成。
/// (この鍵導出を1バイトでも違えると既存の署名済みプロキシ URL が全て
/// 403になるため、Python 側の `.encode()` 対象が16進"文字列"である点を含めて
/// 完全に一致させる必要がある。)
fn signing_key(config: &Config) -> Vec<u8> {
    if !config.media_proxy_key.is_empty() {
        return config.media_proxy_key.as_bytes().to_vec();
    }
    let mut mac = HmacSha256::new_from_slice(config.secret_key.as_bytes())
        .expect("HMAC accepts a key of any length");
    mac.update(b"media-proxy");
    to_hex(&mac.finalize().into_bytes()).into_bytes()
}

fn constant_time_eq(a: &[u8], b: &[u8]) -> bool {
    if a.len() != b.len() {
        return false;
    }
    let mut diff = 0u8;
    for (x, y) in a.iter().zip(b.iter()) {
        diff |= x ^ y;
    }
    diff == 0
}

/// `app.utils.media_proxy.verify_proxy_hmac` を移植したもの。
pub fn verify(config: &Config, url: &str, h: &str) -> bool {
    let key = signing_key(config);
    let mut mac = HmacSha256::new_from_slice(&key).expect("HMAC accepts a key of any length");
    mac.update(url.as_bytes());
    let expected = to_hex(&mac.finalize().into_bytes());
    constant_time_eq(&expected.as_bytes()[..32], h.as_bytes())
}

/// テスト・開発用: 有効な `h` パラメータを生成する
/// (`app.utils.media_proxy.media_proxy_url` の署名部分のみを切り出したもの)。
pub fn sign(config: &Config, url: &str) -> String {
    let key = signing_key(config);
    let mut mac = HmacSha256::new_from_slice(&key).expect("HMAC accepts a key of any length");
    mac.update(url.as_bytes());
    to_hex(&mac.finalize().into_bytes())[..32].to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn test_config() -> Config {
        let mut config = Config::from_env();
        config.secret_key = "test-secret-key-for-hmac-sig-unit-tests".to_string();
        config.media_proxy_key = String::new();
        config
    }

    #[test]
    fn sign_then_verify_round_trips() {
        let config = test_config();
        let url = "https://remote.example/img.png";
        let h = sign(&config, url);
        assert_eq!(h.len(), 32);
        assert!(verify(&config, url, &h));
    }

    #[test]
    fn verify_rejects_tampered_url() {
        let config = test_config();
        let h = sign(&config, "https://remote.example/img.png");
        assert!(!verify(&config, "https://evil.example/img.png", &h));
    }

    #[test]
    fn verify_rejects_wrong_signature() {
        let config = test_config();
        assert!(!verify(
            &config,
            "https://remote.example/img.png",
            "0000000000000000"
        ));
    }

    #[test]
    fn explicit_media_proxy_key_overrides_derivation() {
        let mut config = test_config();
        config.media_proxy_key = "explicit-key".to_string();
        let url = "https://remote.example/img.png";
        let h = sign(&config, url);
        assert!(verify(&config, url, &h));

        // secret_key だけ変えても導出鍵ではなく明示鍵が使われるため結果は同じ。
        let mut other = config.clone();
        other.secret_key = "different-secret".to_string();
        assert!(verify(&other, url, &h));
    }

    /// Python の `_media_proxy_signing_key`/`verify_proxy_hmac` (secret_key から
    /// 導出する既定経路) を実際に実行して得たオラクル値との突き合わせ。
    #[test]
    fn matches_python_oracle() {
        let mut config = test_config();
        config.secret_key = "oracle-secret-key".to_string();
        config.media_proxy_key = String::new();
        let url = "https://remote.example/oracle.png";
        // python3.12 -c 'import hmac,hashlib; key=hmac.new(b"oracle-secret-key", b"media-proxy", hashlib.sha256).hexdigest().encode(); print(hmac.new(key, b"https://remote.example/oracle.png", hashlib.sha256).hexdigest()[:32])'
        let expected = "b8cfd67df770518d2fcbed1a503bb0eb";
        assert_eq!(sign(&config, url), expected);
    }
}
