//! `app/services/drive_service.py` のうち `upload_drive_file`/`delete_drive_file`/
//! `get_drive_file`/`file_to_url`(と、その内部で使うマジックバイト検証・
//! EXIF除去・画像寸法抽出)を移植したもの。`ALLOWED_MEDIA_TYPES`はいずれも
//! バイト列の直接パースのみで完結する(画像デコードライブラリ不要)ため、
//! Python版と1:1で移植できる。`server_file=true`(所有者なし、容量制限
//! チェック対象外)の呼び出し元のみ現状存在する(`admin.rs`のemoji
//! add/import系)ため、`owner`/`quota_service`連携は未移植のまま残す
//! (`app/services/quota_service`がbackend-rsにまだ無い)。

use chrono::{DateTime, Utc};
use uuid::Uuid;

use crate::config::Config;
use crate::error::AppError;
use crate::state::AppState;
use crate::storage;

pub const ALLOWED_IMAGE_TYPES: &[&str] = &[
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/avif",
    "image/apng",
];

const ALLOWED_VIDEO_TYPES: &[&str] = &[
    "video/mp4",
    "video/webm",
    "video/quicktime",
    "video/x-matroska",
];

const ALLOWED_AUDIO_TYPES: &[&str] = &[
    "audio/mpeg",
    "audio/ogg",
    "audio/wav",
    "audio/flac",
    "audio/aac",
    "audio/webm",
    "audio/mp4",
];

fn is_allowed_media_type(mime_type: &str) -> bool {
    ALLOWED_IMAGE_TYPES.contains(&mime_type)
        || ALLOWED_VIDEO_TYPES.contains(&mime_type)
        || ALLOWED_AUDIO_TYPES.contains(&mime_type)
}

#[derive(sqlx::FromRow, Clone)]
pub struct DriveFile {
    pub id: Uuid,
    pub owner_id: Option<Uuid>,
    pub s3_key: String,
    pub filename: String,
    pub mime_type: String,
    pub size_bytes: i64,
    pub width: Option<i32>,
    pub height: Option<i32>,
    pub description: Option<String>,
    pub server_file: bool,
    pub thumbnail_s3_key: Option<String>,
    pub created_at: DateTime<Utc>,
}

/// `app.services.drive_service._validate_magic_bytes`を移植したもの。
fn validate_magic_bytes(data: &[u8], mime_type: &str) -> Result<(), AppError> {
    const FTYP_BRANDS: &[(&str, &[&[u8]])] = &[
        ("image/avif", &[b"avif", b"avis", b"mif1"]),
        (
            "video/mp4",
            &[
                b"isom", b"iso2", b"iso5", b"iso6", b"mp41", b"mp42", b"avc1", b"dash",
            ],
        ),
        ("video/quicktime", &[b"qt  "]),
        ("audio/aac", &[b"isom", b"iso2", b"M4A ", b"mp42"]),
        ("audio/mp4", &[b"isom", b"iso2", b"M4A ", b"mp42"]),
    ];
    if let Some((_, brands)) = FTYP_BRANDS.iter().find(|(m, _)| *m == mime_type) {
        if data.len() >= 12 && &data[4..8] == b"ftyp" && brands.iter().any(|b| &data[8..12] == *b) {
            return Ok(());
        }
        return Err(AppError::new(
            axum::http::StatusCode::UNPROCESSABLE_ENTITY,
            format!("File content does not match declared type {mime_type}"),
        ));
    }

    let signatures: &[&[u8]] = match mime_type {
        "image/jpeg" => &[b"\xff\xd8\xff"],
        "image/png" | "image/apng" => &[b"\x89PNG\r\n\x1a\n"],
        "image/gif" => &[b"GIF87a", b"GIF89a"],
        "image/webp" => &[b"RIFF"],
        "image/avif" => &[b"\x00\x00\x00"],
        "video/webm" | "video/x-matroska" | "audio/webm" => &[b"\x1a\x45\xdf\xa3"],
        "audio/mpeg" => &[b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"],
        "audio/ogg" => &[b"OggS"],
        "audio/wav" => &[b"RIFF"],
        "audio/flac" => &[b"fLaC"],
        _ => return Ok(()), // 検証定義がないMIMEタイプはスキップ
    };
    for sig in signatures {
        if data.len() >= sig.len() && &data[..sig.len()] == *sig {
            return Ok(());
        }
    }
    Err(AppError::new(
        axum::http::StatusCode::UNPROCESSABLE_ENTITY,
        format!("File content does not match declared type {mime_type}"),
    ))
}

const PNG_SIGNATURE: &[u8] = b"\x89PNG\r\n\x1a\n";

/// `app.services.drive_service._remove_jpeg_app1`/`_strip_exif_jpeg`を移植したもの。
fn strip_exif_jpeg(data: &[u8]) -> Vec<u8> {
    if data.len() < 2 || &data[..2] != b"\xff\xd8" {
        return data.to_vec();
    }
    let mut result = Vec::with_capacity(data.len());
    result.extend_from_slice(b"\xff\xd8");
    let mut pos = 2usize;
    while pos < data.len() {
        if data[pos] != 0xFF {
            result.extend_from_slice(&data[pos..]);
            break;
        }
        if pos + 2 > data.len() {
            result.extend_from_slice(&data[pos..]);
            break;
        }
        let marker = &data[pos..pos + 2];
        if marker == b"\xff\xda" {
            result.extend_from_slice(&data[pos..]);
            break;
        }
        // スタンドアロンマーカー (長さフィールドなし)
        if (0xD0..0xDA).contains(&marker[1]) || marker == b"\xff\x01" {
            result.extend_from_slice(marker);
            pos += 2;
            continue;
        }
        if pos + 4 > data.len() {
            result.extend_from_slice(&data[pos..]);
            break;
        }
        let length = u16::from_be_bytes([data[pos + 2], data[pos + 3]]) as usize;
        let segment_end = pos + 2 + length;
        if segment_end > data.len() {
            result.extend_from_slice(&data[pos..]);
            break;
        }
        if marker == b"\xff\xe1" {
            pos = segment_end;
            continue;
        }
        result.extend_from_slice(&data[pos..segment_end]);
        pos = segment_end;
    }
    result
}

/// `app.services.drive_service._strip_exif_png`を移植したもの。
fn strip_exif_png(data: &[u8]) -> Vec<u8> {
    if data.len() < 8 || &data[..8] != PNG_SIGNATURE {
        return data.to_vec();
    }
    let mut result = Vec::with_capacity(data.len());
    result.extend_from_slice(&data[..8]);
    let mut pos = 8usize;
    while pos + 8 <= data.len() {
        let length =
            u32::from_be_bytes([data[pos], data[pos + 1], data[pos + 2], data[pos + 3]]) as usize;
        let chunk_type = &data[pos + 4..pos + 8];
        let chunk_end = pos + 12 + length; // 4(len) + 4(type) + data + 4(crc)
        if chunk_end > data.len() {
            result.extend_from_slice(&data[pos..]);
            break;
        }
        if chunk_type == b"eXIf" {
            pos = chunk_end;
            continue;
        }
        result.extend_from_slice(&data[pos..chunk_end]);
        pos = chunk_end;
    }
    result
}

/// `app.services.drive_service.strip_exif`を移植したもの。画像デコード不要の
/// バイトレベル除去(JPEG: APP1セグメント、PNG: eXIfチャンク)。他フォーマットは
/// そのまま返す。
fn strip_exif(data: &[u8], mime_type: &str) -> Vec<u8> {
    match mime_type {
        "image/jpeg" => strip_exif_jpeg(data),
        "image/png" => strip_exif_png(data),
        _ => data.to_vec(),
    }
}

/// `app.services.drive_service._get_image_dimensions`を移植したもの。
fn get_image_dimensions(data: &[u8], mime_type: &str) -> (Option<i32>, Option<i32>) {
    match mime_type {
        "image/png" if data.len() >= 24 && &data[..8] == PNG_SIGNATURE => (
            Some(i32::from_be_bytes([data[16], data[17], data[18], data[19]])),
            Some(i32::from_be_bytes([data[20], data[21], data[22], data[23]])),
        ),
        "image/jpeg" => {
            let mut i = 2usize;
            while i + 9 < data.len() {
                if data[i] != 0xFF {
                    break;
                }
                let marker = data[i + 1];
                if matches!(marker, 0xC0..=0xC2) {
                    let h = u16::from_be_bytes([data[i + 5], data[i + 6]]) as i32;
                    let w = u16::from_be_bytes([data[i + 7], data[i + 8]]) as i32;
                    return (Some(w), Some(h));
                }
                let length = u16::from_be_bytes([data[i + 2], data[i + 3]]) as usize;
                i += 2 + length;
            }
            (None, None)
        }
        "image/gif" if data.len() >= 10 && &data[..3] == b"GIF" => (
            Some(u16::from_le_bytes([data[6], data[7]]) as i32),
            Some(u16::from_le_bytes([data[8], data[9]]) as i32),
        ),
        "image/webp"
            if data.len() >= 30
                && &data[..4] == b"RIFF"
                && &data[8..12] == b"WEBP"
                && &data[12..16] == b"VP8 " =>
        {
            let w = (u16::from_le_bytes([data[26], data[27]]) & 0x3FFF) as i32;
            let h = (u16::from_le_bytes([data[28], data[29]]) & 0x3FFF) as i32;
            (Some(w), Some(h))
        }
        _ => (None, None),
    }
}

fn extension_for_mime(mime_type: &str) -> &'static str {
    match mime_type {
        "image/jpeg" => ".jpg",
        "image/png" => ".png",
        "image/gif" => ".gif",
        "image/webp" => ".webp",
        "image/avif" => ".avif",
        "image/apng" => ".apng",
        "video/mp4" => ".mp4",
        "video/webm" => ".webm",
        "video/quicktime" => ".mov",
        "video/x-matroska" => ".mkv",
        "audio/mpeg" => ".mp3",
        "audio/ogg" => ".ogg",
        "audio/wav" => ".wav",
        "audio/flac" => ".flac",
        "audio/aac" => ".aac",
        "audio/webm" => ".weba",
        "audio/mp4" => ".m4a",
        _ => "",
    }
}

fn max_size_for_mime(config: &Config, mime_type: &str) -> u64 {
    let mb = if mime_type.starts_with("video/") {
        config.max_video_size_mb
    } else if mime_type.starts_with("audio/") {
        config.max_audio_size_mb
    } else {
        config.max_image_size_mb
    };
    mb * 1024 * 1024
}

/// media-proxy-rs `/transform` へのデコード→再エンコード呼び出し。
/// `app.services.drive_service._reencode_via_transform`を移植したもの。
/// `no_resize=1`を指定し元の解像度を維持する。失敗時は呼び出し元が
/// `strip_exif`にフォールバックする。
async fn reencode_via_transform(config: &Config, data: &[u8]) -> Result<(Vec<u8>, String), ()> {
    let base_url = config.media_proxy_transform_url.as_deref().ok_or(())?;
    let url = if base_url.ends_with("/transform") {
        base_url.to_string()
    } else {
        format!("{}/transform", base_url.trim_end_matches('/'))
    };

    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(
            config.media_proxy_total_timeout_secs,
        ))
        .build()
        .map_err(|_| ())?;
    let part = reqwest::multipart::Part::bytes(data.to_vec())
        .file_name("image")
        .mime_str("application/octet-stream")
        .map_err(|_| ())?;
    let form = reqwest::multipart::Form::new()
        .part("file", part)
        .text("no_resize", "1");

    let resp = client
        .post(&url)
        .multipart(form)
        .send()
        .await
        .map_err(|_| ())?;
    if !resp.status().is_success() {
        return Err(());
    }
    let new_mime = resp
        .headers()
        .get(reqwest::header::CONTENT_TYPE)
        .and_then(|v| v.to_str().ok())
        .map(|v| v.split(';').next().unwrap_or(v).trim().to_string())
        .unwrap_or_else(|| "image/webp".to_string());
    let body = resp.bytes().await.map_err(|_| ())?;
    Ok((body.to_vec(), new_mime))
}

/// `app.services.drive_service.upload_drive_file`を移植したもの。
/// `owner`(容量制限チェック)は`quota_service`が未移植のため現状
/// サポートしない(呼び出し元は`server_file=true`のみを想定)。
#[allow(clippy::too_many_arguments)]
pub async fn upload_drive_file(
    state: &AppState,
    data: Vec<u8>,
    filename: &str,
    mime_type: &str,
    description: Option<&str>,
    server_file: bool,
) -> Result<DriveFile, AppError> {
    let max_size = max_size_for_mime(&state.config, mime_type);
    if data.len() as u64 > max_size {
        return Err(AppError::new(
            axum::http::StatusCode::UNPROCESSABLE_ENTITY,
            format!("File too large (max {} MB)", max_size / 1024 / 1024),
        ));
    }
    if !is_allowed_media_type(mime_type) {
        return Err(AppError::new(
            axum::http::StatusCode::UNPROCESSABLE_ENTITY,
            format!("Unsupported file type: {mime_type}"),
        ));
    }

    validate_magic_bytes(&data, mime_type)?;

    let mut data = data;
    let mut mime_type = mime_type.to_string();
    if mime_type.starts_with("image/") {
        let mut transformed = false;
        if state.config.media_proxy_transform_enabled() {
            match reencode_via_transform(&state.config, &data).await {
                Ok((new_data, new_mime))
                    if ALLOWED_IMAGE_TYPES.contains(&new_mime.as_str())
                        && new_data.len() as u64 <= max_size =>
                {
                    data = new_data;
                    mime_type = new_mime;
                    transformed = true;
                }
                _ => {
                    tracing::warn!("Transform re-encode failed, falling back to strip_exif");
                }
            }
        }
        if !transformed {
            data = strip_exif(&data, &mime_type);
        }
    }

    let file_id = Uuid::new_v4();
    let ext = extension_for_mime(&mime_type);
    // Python版は`owner`がある場合`u/{owner.id}`を使うが、この関数は
    // owner無し(`server_file=true`)の呼び出し元のみ現状サポートする。
    let s3_key = format!("server/{file_id}{ext}");

    let (width, height) = if mime_type.starts_with("image/") {
        get_image_dimensions(&data, &mime_type)
    } else {
        (None, None)
    };

    storage::upload_file(&state.config, &s3_key, &data, &mime_type).await?;

    let now = Utc::now();
    sqlx::query(
        "INSERT INTO drive_files (\
            id, owner_id, s3_key, filename, mime_type, size_bytes, width, height, \
            description, server_file, created_at\
         ) VALUES ($1, NULL, $2, $3, $4, $5, $6, $7, $8, $9, $10)",
    )
    .bind(file_id)
    .bind(&s3_key)
    .bind(filename)
    .bind(&mime_type)
    .bind(data.len() as i64)
    .bind(width)
    .bind(height)
    .bind(description)
    .bind(server_file)
    .bind(now)
    .execute(&state.db)
    .await?;

    Ok(DriveFile {
        id: file_id,
        owner_id: None,
        s3_key,
        filename: filename.to_string(),
        mime_type,
        size_bytes: data.len() as i64,
        width,
        height,
        description: description.map(str::to_string),
        server_file,
        thumbnail_s3_key: None,
        created_at: now,
    })
}

/// `app.services.drive_service.get_drive_file`を移植したもの。
pub async fn get_drive_file(state: &AppState, id: Uuid) -> Result<Option<DriveFile>, AppError> {
    let row = sqlx::query_as(
        "SELECT id, owner_id, s3_key, filename, mime_type, size_bytes, width, height, \
                description, server_file, thumbnail_s3_key, created_at \
         FROM drive_files WHERE id = $1",
    )
    .bind(id)
    .fetch_optional(&state.db)
    .await?;
    Ok(row)
}

/// `app.services.drive_service.delete_drive_file`を移植したもの。
/// サムネイル削除失敗はPython版と同じくベストエフォート(ログのみ)。
pub async fn delete_drive_file(state: &AppState, drive_file: &DriveFile) -> Result<(), AppError> {
    storage::delete_file(&state.config, &drive_file.s3_key).await?;
    if let Some(thumb_key) = &drive_file.thumbnail_s3_key {
        if let Err(err) = storage::delete_file(&state.config, thumb_key).await {
            tracing::warn!(?err, thumb_key, "Failed to delete thumbnail");
        }
    }
    sqlx::query("DELETE FROM drive_files WHERE id = $1")
        .bind(drive_file.id)
        .execute(&state.db)
        .await?;
    Ok(())
}

/// `app.services.drive_service.file_to_url`を移植したもの。
pub fn file_to_url(config: &Config, drive_file: &DriveFile) -> String {
    storage::public_url(config, &drive_file.s3_key)
}

#[cfg(test)]
mod tests {
    use super::*;

    const PNG_1X1: &[u8] = &[
        0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, // signature
        0x00, 0x00, 0x00, 0x0d, b'I', b'H', b'D', b'R', // IHDR chunk header
        0x00, 0x00, 0x00, 0x01, // width = 1
        0x00, 0x00, 0x00, 0x01, // height = 1
        0x08, 0x02, // bit depth, color type
        0x00, 0x00, 0x00, // compression, filter, interlace
        0x90, 0x77, 0x53, 0xde, // crc
    ];

    #[test]
    fn validates_png_magic_bytes() {
        assert!(validate_magic_bytes(PNG_1X1, "image/png").is_ok());
        assert!(validate_magic_bytes(b"not a png", "image/png").is_err());
    }

    #[test]
    fn extracts_png_dimensions() {
        assert_eq!(
            get_image_dimensions(PNG_1X1, "image/png"),
            (Some(1), Some(1))
        );
    }

    #[test]
    fn strip_exif_leaves_non_jpeg_png_untouched() {
        let data = b"RIFF....WEBPVP8 ....";
        assert_eq!(strip_exif(data, "image/webp"), data);
    }
}
