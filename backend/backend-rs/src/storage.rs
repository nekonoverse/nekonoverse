//! `app/storage.py` のうち `ensure_bucket`/`upload_file`/`delete_file`/
//! `download_file` を移植したもの。手書き AWS SigV4 (boto3 非依存) を
//! `reqwest` で踏襲する。`get_file_stream`/`generate_presigned_get_url` は
//! まだ backend-rs 側に呼び出し元が無いため未移植(`download_file`はemoji
//! エクスポート(#1139 Stage 4、`admin.rs`の`export_emojis_endpoint`)が
//! ZIPに書き出す前に画像を丸ごとメモリに読む用途のみで、ストリーミングは
//! 要しない)。

use std::sync::OnceLock;
use std::time::Duration;

use axum::http::StatusCode;
use hmac::{Hmac, Mac};
use sha2::{Digest, Sha256};

use crate::config::Config;
use crate::error::AppError;

type HmacSha256 = Hmac<Sha256>;

static S3_CLIENT: OnceLock<reqwest::Client> = OnceLock::new();

/// `app.storage._get_s3_client`相当のプロセス内共有クライアント。
fn http_client() -> &'static reqwest::Client {
    S3_CLIENT.get_or_init(|| {
        reqwest::Client::builder()
            .timeout(Duration::from_secs(30))
            .build()
            .expect("failed to build S3 http client")
    })
}

fn hmac_sha256(key: &[u8], msg: &str) -> Vec<u8> {
    let mut mac = HmacSha256::new_from_slice(key).expect("HMAC accepts a key of any length");
    mac.update(msg.as_bytes());
    mac.finalize().into_bytes().to_vec()
}

/// `app.storage._signing_key`を移植したもの。
fn signing_key(config: &Config, date_str: &str) -> Vec<u8> {
    let k = hmac_sha256(
        format!("AWS4{}", config.s3_secret_access_key).as_bytes(),
        date_str,
    );
    let k = hmac_sha256(&k, &config.s3_region);
    let k = hmac_sha256(&k, "s3");
    hmac_sha256(&k, "aws4_request")
}

/// `app.storage._endpoint_host`を移植したもの (`urlparse(...).netloc`相当)。
fn endpoint_host(config: &Config) -> Result<String, AppError> {
    let url = reqwest::Url::parse(&config.s3_endpoint_url)
        .map_err(|_| AppError::new(StatusCode::INTERNAL_SERVER_ERROR, "invalid S3 endpoint URL"))?;
    let host = url.host_str().ok_or_else(|| {
        AppError::new(StatusCode::INTERNAL_SERVER_ERROR, "invalid S3 endpoint URL")
    })?;
    Ok(match url.port() {
        Some(port) => format!("{host}:{port}"),
        None => host.to_string(),
    })
}

/// AWS SigV4 の canonical URI エンコード (`urllib.parse.quote(path, safe="/")`相当)。
/// 未予約文字 (`A-Za-z0-9-._~`) と `/` 以外を `%XX` にパーセントエンコードする。
fn uri_encode_path(path: &str) -> String {
    let mut out = String::with_capacity(path.len());
    for b in path.bytes() {
        match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'.' | b'_' | b'~' | b'/' => {
                out.push(b as char)
            }
            _ => out.push_str(&format!("%{b:02X}")),
        }
    }
    out
}

/// `app.storage._auth_headers`を移植したもの。署名済みヘッダー一覧
/// (`Authorization`込み、ソート済み)を返す。
fn auth_headers(
    config: &Config,
    method: &str,
    encoded_path: &str,
    content_sha256: &str,
    extra_headers: &[(&str, String)],
) -> Result<Vec<(String, String)>, AppError> {
    let now = chrono::Utc::now();
    let date_str = now.format("%Y%m%d").to_string();
    let amz_date = now.format("%Y%m%dT%H%M%SZ").to_string();

    let mut headers: Vec<(String, String)> = vec![
        ("host".to_string(), endpoint_host(config)?),
        ("x-amz-date".to_string(), amz_date.clone()),
        (
            "x-amz-content-sha256".to_string(),
            content_sha256.to_string(),
        ),
    ];
    for (k, v) in extra_headers {
        headers.push((k.to_string(), v.clone()));
    }
    headers.sort_by(|a, b| a.0.cmp(&b.0));

    let signed_headers_str = headers
        .iter()
        .map(|(k, _)| k.as_str())
        .collect::<Vec<_>>()
        .join(";");
    let canonical_headers: String = headers.iter().map(|(k, v)| format!("{k}:{v}\n")).collect();

    let canonical_request = [
        method,
        encoded_path,
        "", // canonical query string (このクライアントは常に空)
        &canonical_headers,
        &signed_headers_str,
        content_sha256,
    ]
    .join("\n");

    let credential_scope = format!("{date_str}/{}/s3/aws4_request", config.s3_region);
    let string_to_sign = format!(
        "AWS4-HMAC-SHA256\n{amz_date}\n{credential_scope}\n{:x}",
        Sha256::digest(canonical_request.as_bytes())
    );

    let signature_bytes = {
        let mut mac = HmacSha256::new_from_slice(&signing_key(config, &date_str))
            .expect("HMAC accepts a key of any length");
        mac.update(string_to_sign.as_bytes());
        mac.finalize().into_bytes()
    };
    let signature = format!("{signature_bytes:x}");

    headers.push((
        "Authorization".to_string(),
        format!(
            "AWS4-HMAC-SHA256 Credential={}/{credential_scope}, SignedHeaders={signed_headers_str}, Signature={signature}",
            config.s3_access_key_id
        ),
    ));
    Ok(headers)
}

fn request_error(err: reqwest::Error) -> AppError {
    tracing::error!(error = %err, "S3 request failed");
    AppError::new(StatusCode::INTERNAL_SERVER_ERROR, "Internal server error")
}

fn build_url(config: &Config, encoded_path: &str) -> String {
    format!(
        "{}{encoded_path}",
        config.s3_endpoint_url.trim_end_matches('/')
    )
}

/// `app.storage.ensure_bucket`を移植したもの。バケットが既に存在する場合の
/// `409`もPython版と同じく正常系として扱う。
pub async fn ensure_bucket(config: &Config) -> Result<(), AppError> {
    let path = format!("/{}", config.s3_bucket);
    let encoded_path = uri_encode_path(&path);
    let content_sha256 = format!("{:x}", Sha256::digest(b""));
    let headers = auth_headers(config, "PUT", &encoded_path, &content_sha256, &[])?;

    let mut req = http_client().put(build_url(config, &encoded_path));
    for (k, v) in &headers {
        req = req.header(k.as_str(), v.as_str());
    }
    let resp = req.send().await.map_err(request_error)?;
    if resp.status() != StatusCode::OK && resp.status() != StatusCode::CONFLICT {
        tracing::warn!(status = %resp.status(), "S3 ensure_bucket returned unexpected status");
    }
    Ok(())
}

/// `app.storage.upload_file`を移植したもの。
pub async fn upload_file(
    config: &Config,
    key: &str,
    data: &[u8],
    content_type: &str,
) -> Result<(), AppError> {
    let path = format!("/{}/{key}", config.s3_bucket);
    let encoded_path = uri_encode_path(&path);
    let content_sha256 = format!("{:x}", Sha256::digest(data));
    let headers = auth_headers(
        config,
        "PUT",
        &encoded_path,
        &content_sha256,
        &[("content-type", content_type.to_string())],
    )?;

    let mut req = http_client()
        .put(build_url(config, &encoded_path))
        .body(data.to_vec());
    for (k, v) in &headers {
        req = req.header(k.as_str(), v.as_str());
    }
    let resp = req.send().await.map_err(request_error)?;
    if !resp.status().is_success() {
        tracing::error!(status = %resp.status(), key, "S3 upload failed");
        return Err(AppError::new(
            StatusCode::INTERNAL_SERVER_ERROR,
            "Internal server error",
        ));
    }
    Ok(())
}

/// `app.storage.delete_file`を移植したもの。`404`(既に存在しない)も
/// Python版と同じく正常系として扱う。
pub async fn delete_file(config: &Config, key: &str) -> Result<(), AppError> {
    let path = format!("/{}/{key}", config.s3_bucket);
    let encoded_path = uri_encode_path(&path);
    let content_sha256 = format!("{:x}", Sha256::digest(b""));
    let headers = auth_headers(config, "DELETE", &encoded_path, &content_sha256, &[])?;

    let mut req = http_client().delete(build_url(config, &encoded_path));
    for (k, v) in &headers {
        req = req.header(k.as_str(), v.as_str());
    }
    let resp = req.send().await.map_err(request_error)?;
    let status = resp.status();
    if status != StatusCode::OK
        && status != StatusCode::NO_CONTENT
        && status != StatusCode::NOT_FOUND
    {
        tracing::error!(status = %status, key, "S3 delete failed");
        return Err(AppError::new(
            StatusCode::INTERNAL_SERVER_ERROR,
            "Internal server error",
        ));
    }
    Ok(())
}

/// `app.storage.get_public_url`を移植したもの。
pub fn public_url(config: &Config, key: &str) -> String {
    format!("{}/{key}", config.media_url())
}

/// `app.storage.download_file`を移植したもの。`404`は`None`として返す
/// (Python版は`resp.raise_for_status()`で例外化するが、呼び出し元の
/// `export_emojis_endpoint`は「S3上に実体が無ければそのカスタム絵文字を
/// ZIPから静かに除外する」ベストエフォート処理のため、backend-rs側は
/// エラーと未検出を呼び出し元で区別できるよう`Option`にした)。
/// Python版の`download_file`/`get_file_stream`と同じく`content_sha256`に
/// 実ハッシュではなく`"UNSIGNED-PAYLOAD"`を使う(GETはボディが無いため
/// `upload_file`/`delete_file`の空文字列ハッシュと等価だが、Python版の
/// 実際の挙動をそのまま踏襲する)。
pub async fn get_file(config: &Config, key: &str) -> Result<Option<Vec<u8>>, AppError> {
    let path = format!("/{}/{key}", config.s3_bucket);
    let encoded_path = uri_encode_path(&path);
    let headers = auth_headers(config, "GET", &encoded_path, "UNSIGNED-PAYLOAD", &[])?;

    let mut req = http_client().get(build_url(config, &encoded_path));
    for (k, v) in &headers {
        req = req.header(k.as_str(), v.as_str());
    }
    let resp = req.send().await.map_err(request_error)?;
    if resp.status() == StatusCode::NOT_FOUND {
        return Ok(None);
    }
    if !resp.status().is_success() {
        tracing::error!(status = %resp.status(), key, "S3 get failed");
        return Err(AppError::new(
            StatusCode::INTERNAL_SERVER_ERROR,
            "Internal server error",
        ));
    }
    let bytes = resp.bytes().await.map_err(request_error)?;
    Ok(Some(bytes.to_vec()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn uri_encode_path_keeps_slashes_and_unreserved_chars() {
        assert_eq!(
            uri_encode_path("/bucket/server/abc-123.png"),
            "/bucket/server/abc-123.png"
        );
    }

    #[test]
    fn uri_encode_path_escapes_reserved_chars() {
        assert_eq!(uri_encode_path("/bucket/a b+c"), "/bucket/a%20b%2Bc");
    }
}
