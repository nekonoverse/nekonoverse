//! `app/utils/media_proxy.py` の HMAC 署名検証部分を移植したもの。
//! `verify`(検証)に加え、`media_proxy_url`(生成)も
//! `accounts.py` のアカウント関係性系エンドポイント移植 (Stage 4) で
//! 必要になったためこちらに実装する。Python側の `statuses.py`/`accounts.py`
//! の未移植部分は引き続き独自に生成するため、両実装が同じ鍵導出・署名規則
//! (`sign`) に従う必要がある。

use hmac::{Hmac, Mac};
use sha2::Sha256;

use crate::config::Config;

type HmacSha256 = Hmac<Sha256>;

/// OAuth トークンのハッシュ化 (`auth` モジュール) でも使う小さな共通ヘルパー。
pub(crate) fn to_hex(bytes: &[u8]) -> String {
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

/// `app.utils.media_proxy.media_proxy_url` の署名部分のみを切り出したもの
/// (テストからも `media_proxy_url` からも使う)。
pub fn sign(config: &Config, url: &str) -> String {
    let key = signing_key(config);
    let mut mac = HmacSha256::new_from_slice(&key).expect("HMAC accepts a key of any length");
    mac.update(url.as_bytes());
    to_hex(&mac.finalize().into_bytes())[..32].to_string()
}

/// `app.utils.media_proxy._is_local_url` を移植したもの。
/// 自サーバーの URL (相対パス、または scheme+host が一致する絶対URL) か判定する。
fn is_local_media_url(config: &Config, url: &str) -> bool {
    if url.starts_with('/') {
        // "//host" や "/\\host" はブラウザが別ホストとして解釈するため除外する。
        return !url.starts_with("//") && !url.starts_with("/\\");
    }
    let (Ok(local), Ok(parsed)) = (
        reqwest::Url::parse(&config.server_url()),
        reqwest::Url::parse(url),
    ) else {
        return false;
    };
    local.scheme() == parsed.scheme()
        && local.host_str() == parsed.host_str()
        && local.port() == parsed.port()
}

/// `urllib.parse.quote(url, safe='')` を移植したもの
/// (RFC 3986 の unreserved 文字以外を全て `%XX` にエンコードする)。
fn percent_encode_quote_safe_empty(input: &str) -> String {
    let mut out = String::with_capacity(input.len());
    for byte in input.bytes() {
        match byte {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'_' | b'.' | b'-' | b'~' => {
                out.push(byte as char)
            }
            _ => out.push_str(&format!("%{byte:02X}")),
        }
    }
    out
}

/// `app.utils.media_proxy.media_proxy_url` を移植したもの。
/// リモート URL を HMAC 署名付きプロキシ URL に変換する。ローカル URL は
/// そのまま返す。`variant` は Misskey 互換プリセット (`"avatar"`/`"emoji"`等)。
pub fn media_proxy_url(
    config: &Config,
    original_url: Option<&str>,
    variant: Option<&str>,
    static_: bool,
) -> String {
    let Some(original_url) = original_url.filter(|s| !s.is_empty()) else {
        return String::new();
    };
    if is_local_media_url(config, original_url) {
        return original_url.to_string();
    }
    let h = sign(config, original_url);
    let mut url = format!(
        "{}/api/v1/media/proxy?url={}&h={h}",
        config.server_url(),
        percent_encode_quote_safe_empty(original_url),
    );
    if let Some(variant) = variant {
        url.push('&');
        url.push_str(variant);
        url.push_str("=1");
    }
    if static_ {
        url.push_str("&static=1");
    }
    url
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

    #[test]
    fn media_proxy_url_empty_for_none_or_empty_input() {
        let config = test_config();
        assert_eq!(media_proxy_url(&config, None, None, false), "");
        assert_eq!(media_proxy_url(&config, Some(""), None, false), "");
    }

    #[test]
    fn media_proxy_url_passes_through_local_relative_path() {
        let config = test_config();
        assert_eq!(
            media_proxy_url(&config, Some("/media/foo.png"), None, false),
            "/media/foo.png"
        );
    }

    #[test]
    fn media_proxy_url_passes_through_local_absolute_url() {
        let config = test_config();
        let local = format!("{}/media/foo.png", config.server_url());
        assert_eq!(media_proxy_url(&config, Some(&local), None, false), local);
    }

    #[test]
    fn media_proxy_url_rejects_protocol_relative_path() {
        let config = test_config();
        // "//evil.example/x" はブラウザが別ホストとして解釈するためプロキシ対象。
        let result = media_proxy_url(&config, Some("//evil.example/x"), None, false);
        assert!(result.starts_with(&format!("{}/api/v1/media/proxy?", config.server_url())));
    }

    #[test]
    fn media_proxy_url_signs_and_encodes_remote_url() {
        let config = test_config();
        let remote = "https://remote.example/a b.png?x=1&y=2";
        let result = media_proxy_url(&config, Some(remote), Some("avatar"), true);
        let expected_h = sign(&config, remote);
        assert_eq!(
            result,
            format!(
                "{}/api/v1/media/proxy?url=https%3A%2F%2Fremote.example%2Fa%20b.png%3Fx%3D1%26y%3D2&h={expected_h}&avatar=1&static=1",
                config.server_url()
            )
        );
        assert!(verify(&config, remote, &expected_h));
    }
}
