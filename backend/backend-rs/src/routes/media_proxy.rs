use std::time::Duration;

use axum::extract::{Query, State};
use axum::http::{header, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::get;
use axum::Router;
use reqwest::Url;
use serde::Deserialize;
use tokio_stream::StreamExt;

use crate::config::Config;
use crate::error::AppError;
use crate::hmac_sig;
use crate::ssrf;
use crate::state::AppState;

const MAX_SIZE: usize = 20 * 1024 * 1024; // 20 MB
const ALLOWED_CONTENT_PREFIXES: &[&str] = &["image/", "video/", "audio/"];
const CONNECT_TIMEOUT: Duration = Duration::from_secs(5);
const REQUEST_TIMEOUT: Duration = Duration::from_secs(10);
const TRANSFORM_TIMEOUT: Duration = Duration::from_secs(15);
const PROXY_RESPONSE_CSP: &str =
    "default-src 'none'; img-src data:; style-src 'unsafe-inline'; sandbox";

// Content-Type が信頼できない場合の画像検出用マジックバイトシグネチャ。
// `app/api/mastodon/media_proxy.py` の `_IMAGE_SIGNATURES` と同一。
const IMAGE_SIGNATURES: &[(&[u8], &str)] = &[
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"RIFF", "image/webp"),
    (b"BM", "image/bmp"),
    (b"II\x2a\x00", "image/tiff"),
    (b"MM\x00\x2a", "image/tiff"),
    (b"\xff\x0a", "image/jxl"),
    (b"\x00\x00\x00\x0c\x4a\x58\x4c\x20", "image/jxl"),
];

pub fn router() -> Router<AppState> {
    Router::new().route("/api/v1/media/proxy", get(proxy_media))
}

#[derive(Deserialize)]
struct ProxyQuery {
    url: Option<String>,
    h: Option<String>,
    avatar: Option<i64>,
    emoji: Option<i64>,
    preview: Option<i64>,
    #[serde(rename = "static")]
    static_flag: Option<i64>,
    badge: Option<i64>,
}

/// `app/api/mastodon/media_proxy.py` の `_detect_image_type` を移植したもの。
fn detect_image_type(head: &[u8]) -> Option<&'static str> {
    for &(sig, mime) in IMAGE_SIGNATURES {
        if head.len() >= sig.len() && &head[..sig.len()] == sig {
            if sig == b"RIFF" && head.get(8..12) != Some(b"WEBP".as_slice()) {
                continue;
            }
            return Some(mime);
        }
    }
    if head.len() >= 12 && &head[4..8] == b"ftyp" {
        let brand = &head[8..12];
        if [
            b"avif".as_slice(),
            b"avis".as_slice(),
            b"mif1".as_slice(),
            b"heic".as_slice(),
            b"heix".as_slice(),
        ]
        .contains(&brand)
        {
            return Some("image/avif");
        }
    }
    None
}

/// 指定ホストが SSRF 保護でブロック対象かを判定する。
/// `app/utils/network.py` の `is_private_host` を移植したもの
/// (DNS解決不可も含め、レンジに一致すればブロック)。
pub(crate) async fn is_host_blocked(host: &str) -> bool {
    match tokio::net::lookup_host((host, 0)).await {
        Ok(addrs) => addrs.map(|a| a.ip()).any(ssrf::is_blocked_ip),
        Err(_) => true,
    }
}

/// 指定 URL への接続専用クライアントを構築する。SSRF 保護が有効な場合、
/// ホスト名を事前に解決・検証し、検証済みの IP へ直接接続するよう
/// `resolve()` で強制する (DNS リバインディング対策。
/// `app/utils/http_client.py` の `_SSRFGuardBackend` に相当)。
pub(crate) async fn build_client_for(
    url: &Url,
    allow_private_networks: bool,
) -> Result<reqwest::Client, ()> {
    let mut builder = reqwest::Client::builder()
        .connect_timeout(CONNECT_TIMEOUT)
        .timeout(REQUEST_TIMEOUT)
        .redirect(reqwest::redirect::Policy::none());

    if !allow_private_networks {
        let host = url.host_str().ok_or(())?;
        let port = url.port_or_known_default().unwrap_or(80);
        let addrs: Vec<_> = tokio::net::lookup_host((host, port))
            .await
            .map_err(|_| ())?
            .collect();
        if addrs.is_empty() || addrs.iter().any(|a| ssrf::is_blocked_ip(a.ip())) {
            return Err(());
        }
        builder = builder.resolve(host, addrs[0]);
    }

    builder.build().map_err(|_| ())
}

/// `app/api/mastodon/media_proxy.py` の `_fetch_media` を移植したもの。
/// リダイレクトを各ホップで SSRF 検証しつつ、サイズ上限付きでメディアを取得する。
async fn fetch_media(config: &Config, start_url: &str) -> Result<(String, Vec<u8>), AppError> {
    let mut current = start_url.to_string();

    for _ in 0..3 {
        let parsed = Url::parse(&current)
            .map_err(|_| AppError::new(StatusCode::BAD_GATEWAY, "Upstream fetch failed"))?;

        let client = build_client_for(&parsed, config.allow_private_networks)
            .await
            .map_err(|_| AppError::new(StatusCode::BAD_GATEWAY, "Upstream fetch failed"))?;

        let resp = client
            .get(parsed.clone())
            .send()
            .await
            .map_err(|_| AppError::new(StatusCode::BAD_GATEWAY, "Upstream fetch failed"))?;

        if matches!(resp.status().as_u16(), 301 | 302 | 303 | 307 | 308) {
            let location = resp
                .headers()
                .get(header::LOCATION)
                .and_then(|v| v.to_str().ok())
                .ok_or_else(|| AppError::new(StatusCode::BAD_GATEWAY, "Redirect without location"))?
                .to_string();
            let resolved = parsed
                .join(&location)
                .map_err(|_| AppError::new(StatusCode::FORBIDDEN, "Invalid redirect URL"))?;
            if resolved.scheme() != "http" && resolved.scheme() != "https" {
                return Err(AppError::new(StatusCode::FORBIDDEN, "Invalid redirect URL"));
            }
            let Some(redirect_host) = resolved.host_str() else {
                return Err(AppError::new(StatusCode::FORBIDDEN, "Invalid redirect URL"));
            };
            if !config.allow_private_networks && is_host_blocked(redirect_host).await {
                return Err(AppError::new(
                    StatusCode::FORBIDDEN,
                    "Forbidden redirect host",
                ));
            }
            current = resolved.to_string();
            continue;
        }

        if resp.status() != StatusCode::OK {
            return Err(AppError::new(
                StatusCode::BAD_GATEWAY,
                "Upstream returned non-200",
            ));
        }

        if let Some(len) = resp.content_length() {
            if len as usize > MAX_SIZE {
                return Err(AppError::new(
                    StatusCode::PAYLOAD_TOO_LARGE,
                    "Response too large",
                ));
            }
        }

        let content_type = resp
            .headers()
            .get(header::CONTENT_TYPE)
            .and_then(|v| v.to_str().ok())
            .unwrap_or("")
            .to_string();

        let mut body = Vec::new();
        let mut stream = resp.bytes_stream();
        while let Some(chunk) = stream.next().await {
            let chunk = chunk
                .map_err(|_| AppError::new(StatusCode::BAD_GATEWAY, "Upstream fetch failed"))?;
            if body.len() + chunk.len() > MAX_SIZE {
                return Err(AppError::new(
                    StatusCode::PAYLOAD_TOO_LARGE,
                    "Response too large",
                ));
            }
            body.extend_from_slice(&chunk);
        }

        return Ok((content_type, body));
    }

    Err(AppError::new(StatusCode::BAD_GATEWAY, "Too many redirects"))
}

/// `app/api/mastodon/media_proxy.py` の `_transform_image` を移植したもの。
/// media-proxy-rs (TCP) が設定されていれば送信し、失敗時は元画像のバイト列を
/// `image/webp` として返す (Python版のフォールバックと同じ、実際の変換有無に
/// 関わらず content-type は常に webp を主張する点も踏襲)。
///
/// NOTE: `MEDIA_PROXY_TRANSFORM_UDS` は現状未対応。TCP URL が未設定の場合は
/// 呼び出し元でスキップされる (`Config::media_proxy_transform_enabled`)。
async fn transform_image(
    transform_url: &str,
    body: Vec<u8>,
    avatar: Option<i64>,
    emoji: Option<i64>,
    preview: Option<i64>,
    static_flag: Option<i64>,
    badge: Option<i64>,
) -> (Vec<u8>, String) {
    let endpoint = if transform_url.ends_with("/transform") {
        transform_url.to_string()
    } else {
        format!("{transform_url}/transform")
    };

    let mut form = match reqwest::multipart::Part::bytes(body.clone())
        .file_name("image")
        .mime_str("application/octet-stream")
    {
        Ok(part) => reqwest::multipart::Form::new().part("file", part),
        Err(_) => return (body, "image/webp".to_string()),
    };
    for (key, value) in [
        ("avatar", avatar),
        ("emoji", emoji),
        ("preview", preview),
        ("static", static_flag),
        ("badge", badge),
    ] {
        if let Some(v) = value {
            if v != 0 {
                form = form.text(key, v.to_string());
            }
        }
    }

    let client = match reqwest::Client::builder()
        .timeout(TRANSFORM_TIMEOUT)
        .build()
    {
        Ok(c) => c,
        Err(_) => return (body, "image/webp".to_string()),
    };

    match client.post(&endpoint).multipart(form).send().await {
        Ok(resp) if resp.status() == StatusCode::OK => {
            let content_type = resp
                .headers()
                .get(header::CONTENT_TYPE)
                .and_then(|v| v.to_str().ok())
                .unwrap_or("image/webp")
                .to_string();
            match resp.bytes().await {
                Ok(bytes) => (bytes.to_vec(), content_type),
                Err(_) => (body, "image/webp".to_string()),
            }
        }
        Ok(resp) => {
            tracing::warn!(status = %resp.status(), "media transform returned non-200");
            (body, "image/webp".to_string())
        }
        Err(e) => {
            tracing::warn!(error = %e, "media transform failed; serving original image");
            (body, "image/webp".to_string())
        }
    }
}

/// `app/api/mastodon/media_proxy.py` の `proxy_media` を移植したもの。
async fn proxy_media(
    State(state): State<AppState>,
    Query(params): Query<ProxyQuery>,
) -> Result<Response, AppError> {
    let url = params
        .url
        .filter(|s| !s.is_empty())
        .ok_or_else(|| AppError::new(StatusCode::UNPROCESSABLE_ENTITY, "Field required"))?;
    let h = params
        .h
        .filter(|s| (16..=32).contains(&s.len()))
        .ok_or_else(|| AppError::new(StatusCode::UNPROCESSABLE_ENTITY, "Field required"))?;

    if !hmac_sig::verify(&state.config, &url, &h) {
        return Err(AppError::new(StatusCode::FORBIDDEN, "Invalid signature"));
    }

    let parsed =
        Url::parse(&url).map_err(|_| AppError::new(StatusCode::FORBIDDEN, "Invalid URL scheme"))?;
    if parsed.scheme() != "http" && parsed.scheme() != "https" {
        return Err(AppError::new(StatusCode::FORBIDDEN, "Invalid URL scheme"));
    }
    let Some(host) = parsed.host_str() else {
        return Err(AppError::new(StatusCode::FORBIDDEN, "Invalid URL scheme"));
    };

    if !state.config.allow_private_networks && is_host_blocked(host).await {
        return Err(AppError::new(StatusCode::FORBIDDEN, "Forbidden host"));
    }

    let total_timeout = Duration::from_secs(state.config.media_proxy_total_timeout_secs);
    let (mut content_type, mut body) =
        match tokio::time::timeout(total_timeout, fetch_media(&state.config, &url)).await {
            Ok(result) => result?,
            Err(_) => {
                return Err(AppError::new(
                    StatusCode::GATEWAY_TIMEOUT,
                    "Upstream fetch timed out",
                ))
            }
        };

    if !ALLOWED_CONTENT_PREFIXES
        .iter()
        .any(|p| content_type.starts_with(p))
    {
        let head_len = body.len().min(12);
        let detected = detect_image_type(&body[..head_len]);
        match detected {
            Some(mime) => content_type = mime.to_string(),
            None => {
                return Err(AppError::new(
                    StatusCode::FORBIDDEN,
                    "Disallowed content type",
                ))
            }
        }
    }

    let needs_transform = [
        params.avatar,
        params.emoji,
        params.preview,
        params.static_flag,
        params.badge,
    ]
    .iter()
    .any(|v| matches!(v, Some(x) if *x != 0));

    if needs_transform && content_type.starts_with("image/") {
        if let Some(transform_url) = state.config.media_proxy_transform_url.as_deref() {
            let (new_body, new_content_type) = transform_image(
                transform_url,
                body,
                params.avatar,
                params.emoji,
                params.preview,
                params.static_flag,
                params.badge,
            )
            .await;
            body = new_body;
            content_type = new_content_type;
        }
    }

    Ok((
        StatusCode::OK,
        [
            (header::CONTENT_TYPE, content_type.as_str()),
            (header::CACHE_CONTROL, "public, max-age=86400"),
            (header::CONTENT_SECURITY_POLICY, PROXY_RESPONSE_CSP),
            (header::X_CONTENT_TYPE_OPTIONS, "nosniff"),
        ],
        body,
    )
        .into_response())
}
