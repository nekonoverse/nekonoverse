//! `app/activitypub/http_signature.py` の検証側 (`parse_signature_header`/
//! `verify_signature`) と `app/activitypub/routes.py` の `_verify_digest` を
//! 移植したもの。
//!
//! cavage形式 HTTP Signature の検証(RSA-PKCS1v15+SHA256、Ed25519/FEP-521a
//! Multikey の2方式)は、inbox 受信処理(`activitypub/handlers/`)を
//! Rust化する前提となる基盤部品(Issue #1139 Stage 4)。`get_actor_public_key`
//! (鍵IDからactorを引く経路)は未知のリモートactorに対して署名付きHTTPで
//! 取り込む`fetch_remote_actor`に依存しており、これは`resolve_webfinger`と
//! 同種の新たな対外通信能力を要する別の大きな一枚岩のため、本PRでは検証
//! ロジック本体(鍵材料は呼び出し側から渡される前提)のみを切り出す。
//! `sign_request`(配送用の署名生成側)は実配送が引き続きPython側の
//! delivery workerで行われるため未移植。
//!
//! なお `verify_signature`/`_verify_digest` は inbox エンドポイントという
//! 連合の認証境界を担うセキュリティ上重要なロジックのため、Python実装との
//! 一言一句の挙動一致(異常系のフォールスルー含む)を優先して移植している。

use std::collections::{HashMap, HashSet};

use base64::engine::general_purpose::STANDARD as BASE64;
use base64::Engine;
use chrono::{DateTime, Utc};
use ed25519_dalek::{Signature as Ed25519Signature, Verifier, VerifyingKey};
use rsa::pkcs1::DecodeRsaPublicKey;
use rsa::pkcs1v15::Pkcs1v15Sign;
use rsa::pkcs8::DecodePublicKey;
use rsa::RsaPublicKey;
use sha2::{Digest, Sha256};

use crate::hmac_sig::constant_time_eq;
use nekonoverse_core::crypto::ed25519_multibase_to_public_bytes;

/// `app.activitypub.http_signature.parse_signature_header` を移植したもの。
pub fn parse_signature_header(sig_header: &str) -> HashMap<String, String> {
    let mut params = HashMap::new();
    for part in sig_header.split(',') {
        let part = part.trim();
        let Some((key, value)) = part.split_once('=') else {
            continue;
        };
        params.insert(
            key.trim().to_string(),
            value.trim().trim_matches('"').to_string(),
        );
    }
    params
}

/// RFC 2822 (obsolete zone名を含む) の `Date` ヘッダーからの許容ズレ。
/// `app.activitypub.http_signature.verify_signature` と同一 (12時間)。
const DATE_TOLERANCE_SECONDS: i64 = 43200;

/// `app.activitypub.http_signature.verify_signature` を移植したもの。
///
/// `public_key_material` は RSA PEM (`-----BEGIN PUBLIC KEY-----`
/// または `-----BEGIN RSA PUBLIC KEY-----`) か、Ed25519 Multikey
/// (`z6Mk...`) のいずれか。`headers` はヘッダー名を小文字化済みで渡すこと。
pub fn verify_signature(
    public_key_material: &str,
    signature_header: &str,
    method: &str,
    path: &str,
    headers: &HashMap<String, String>,
    algorithm_hint: Option<&str>,
) -> bool {
    let params = parse_signature_header(signature_header);

    let (Some(signature_b64), Some(headers_param), Some(_key_id)) = (
        params.get("signature"),
        params.get("headers"),
        params.get("keyId"),
    ) else {
        return false;
    };

    let signed_headers: Vec<&str> = headers_param.split_whitespace().collect();

    let mut required_headers: HashSet<&str> = HashSet::from(["(request-target)", "date"]);
    if method.eq_ignore_ascii_case("POST") {
        required_headers.insert("digest");
    }
    let signed_headers_lower: HashSet<String> =
        signed_headers.iter().map(|h| h.to_lowercase()).collect();
    if !required_headers
        .iter()
        .all(|h| signed_headers_lower.contains(*h))
    {
        return false;
    }

    let Some(date_header) = headers.get("date") else {
        return false;
    };
    if !is_fresh_date(date_header) {
        return false;
    }

    let signed_parts: Vec<String> = signed_headers
        .iter()
        .map(|h| {
            if *h == "(request-target)" {
                format!("(request-target): {} {path}", method.to_lowercase())
            } else {
                let value = headers.get(&h.to_lowercase()).cloned().unwrap_or_default();
                format!("{}: {value}", h.to_lowercase())
            }
        })
        .collect();
    let signed_string = signed_parts.join("\n");

    let is_multibase = public_key_material.starts_with('z');

    let declared = params
        .get("algorithm")
        .map(|s| s.to_lowercase())
        .unwrap_or_default();
    let algo: &str = match declared.as_str() {
        "ed25519" => "ed25519",
        "rsa-sha256" => "rsa-sha256",
        "hs2019" | "" => algorithm_hint.unwrap_or(if is_multibase {
            "ed25519"
        } else {
            "rsa-sha256"
        }),
        _ => return false,
    };

    if algo == "ed25519" && !is_multibase {
        return false;
    }
    if algo == "rsa-sha256" && is_multibase {
        return false;
    }

    let Ok(signature_bytes) = BASE64.decode(signature_b64) else {
        return false;
    };

    if algo == "rsa-sha256" {
        verify_rsa_sha256(
            public_key_material,
            signed_string.as_bytes(),
            &signature_bytes,
        )
    } else {
        verify_ed25519(
            public_key_material,
            signed_string.as_bytes(),
            &signature_bytes,
        )
    }
}

/// `Date` ヘッダー (RFC 2822、`GMT`等の obsolete zone名を含む) をパースし、
/// 現在時刻との差が `DATE_TOLERANCE_SECONDS` 以内かを判定する。
/// パース失敗も鮮度チェック不合格として扱う (Python版の `except Exception:
/// return False` と同じ)。
fn is_fresh_date(date_header: &str) -> bool {
    let Ok(request_date) = DateTime::parse_from_rfc2822(date_header) else {
        return false;
    };
    let now = Utc::now();
    (now - request_date.with_timezone(&Utc)).num_seconds().abs() <= DATE_TOLERANCE_SECONDS
}

/// PEM (SPKI `BEGIN PUBLIC KEY` または PKCS1 `BEGIN RSA PUBLIC KEY`) を
/// 両対応でパースする。`cryptography.hazmat.primitives.serialization
/// .load_pem_public_key` が PEM ヘッダーから自動判別するのと同じ挙動。
fn parse_rsa_public_key_pem(pem: &str) -> Option<RsaPublicKey> {
    RsaPublicKey::from_public_key_pem(pem)
        .ok()
        .or_else(|| RsaPublicKey::from_pkcs1_pem(pem).ok())
}

fn verify_rsa_sha256(public_key_pem: &str, message: &[u8], signature: &[u8]) -> bool {
    let Some(public_key) = parse_rsa_public_key_pem(public_key_pem) else {
        return false;
    };
    let hashed = Sha256::digest(message);
    public_key
        .verify(Pkcs1v15Sign::new::<Sha256>(), &hashed, signature)
        .is_ok()
}

fn verify_ed25519(multibase: &str, message: &[u8], signature: &[u8]) -> bool {
    let Ok(raw) = ed25519_multibase_to_public_bytes(multibase) else {
        return false;
    };
    let Ok(key_bytes): Result<[u8; 32], _> = raw.try_into() else {
        return false;
    };
    let Ok(verifying_key) = VerifyingKey::from_bytes(&key_bytes) else {
        return false;
    };
    let Ok(sig_bytes): Result<[u8; 64], _> = signature.try_into() else {
        return false;
    };
    let signature = Ed25519Signature::from_bytes(&sig_bytes);
    verifying_key.verify(message, &signature).is_ok()
}

/// `app/activitypub/routes.py` の `_verify_digest` を移植したもの。
/// `Digest: SHA-256=<base64>` ヘッダーが実際のリクエストボディのハッシュと
/// 一致するかをタイミングセーフに検証する。
pub fn verify_digest(body: &[u8], digest_header: Option<&str>) -> bool {
    let Some(digest_header) = digest_header else {
        return false;
    };
    let Some(expected_b64) = digest_header.strip_prefix("SHA-256=") else {
        return false;
    };
    if expected_b64.is_empty() {
        return false;
    }
    let actual_b64 = BASE64.encode(Sha256::digest(body));
    constant_time_eq(actual_b64.as_bytes(), expected_b64.as_bytes())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn headers_map(pairs: &[(&str, &str)]) -> HashMap<String, String> {
        pairs
            .iter()
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect()
    }

    #[test]
    fn parse_signature_header_extracts_quoted_params() {
        let params = parse_signature_header(
            r#"keyId="https://example.com/users/alice#main-key",algorithm="rsa-sha256",headers="(request-target) host date",signature="abc123""#,
        );
        assert_eq!(
            params.get("keyId").unwrap(),
            "https://example.com/users/alice#main-key"
        );
        assert_eq!(params.get("algorithm").unwrap(), "rsa-sha256");
        assert_eq!(params.get("headers").unwrap(), "(request-target) host date");
        assert_eq!(params.get("signature").unwrap(), "abc123");
    }

    #[test]
    fn parse_signature_header_ignores_parts_without_equals() {
        let params = parse_signature_header("keyId=\"a\", garbage, algorithm=\"rsa-sha256\"");
        assert_eq!(params.len(), 2);
    }

    #[test]
    fn verify_digest_matches_sha256_of_body() {
        let body = b"hello world";
        let hash_b64 = BASE64.encode(Sha256::digest(body));
        let header = format!("SHA-256={hash_b64}");
        assert!(verify_digest(body, Some(&header)));
    }

    #[test]
    fn verify_digest_rejects_tampered_body() {
        let body = b"hello world";
        let hash_b64 = BASE64.encode(Sha256::digest(body));
        let header = format!("SHA-256={hash_b64}");
        assert!(!verify_digest(b"hello world!", Some(&header)));
    }

    #[test]
    fn verify_digest_rejects_missing_or_malformed_header() {
        assert!(!verify_digest(b"x", None));
        assert!(!verify_digest(b"x", Some("")));
        assert!(!verify_digest(b"x", Some("MD5=abcd")));
        assert!(!verify_digest(b"x", Some("SHA-256=")));
    }

    // 以下、RSA/Ed25519 の鍵・署名は `app/activitypub/http_signature.py` の
    // 実装(`sign_request`/`generate_ed25519_keypair`)を使って生成したオラクル
    // 値。日時に依存する鮮度チェックは `verify_rsa_sha256`/`verify_ed25519`
    // (署名検証のみを行う下位関数)を直接叩くことで回避し、テストが将来
    // (12時間以上経過後)も腐らないようにしている。生成に使ったスクリプト:
    //
    // ```python
    // from app.activitypub.http_signature import sign_request, parse_signature_header
    // from app.utils.crypto import generate_ed25519_keypair
    // from cryptography.hazmat.primitives import serialization
    // from cryptography.hazmat.primitives.asymmetric import rsa
    //
    // rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    // rsa_private_pem = rsa_key.private_bytes(serialization.Encoding.PEM,
    //     serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    // headers = sign_request(rsa_private_pem, "https://remote.example/users/alice#main-key",
    //     "POST", "https://neko.example/users/bob/inbox", body=BODY, algorithm="rsa-sha256")
    // # public_key_pem, signed_string, signature_b64 を出力
    // ```
    // (Ed25519 も `generate_ed25519_keypair()` + `sign_request(..., algorithm="ed25519")` で同様)

    const RSA_ORACLE_PUBLIC_KEY_PEM: &str = "-----BEGIN PUBLIC KEY-----\n\
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA7IRu2SimXsT+okxRJ2Ce\n\
/uPmcNSg4YzAXC/P0Lelc5NH6l2gEnPGTnilaGiEp2O6uBIHgNCIrcHXIwQC9oWb\n\
tipBGKcM1rnnLEA/7Nm9D6kQh1LOmlE7K+NYyWt+8Bx1FPQTUed/KmjIn0AMTxwf\n\
J4YQiKL24D7WHFylEF2akUCoEaZ5oJQeQ1Mc+CfgWYxeBayhdC9i/vioIzP+B0mJ\n\
uRHV9cmunB6EgTEN64BuKOER4v6E8iSY8J8vlqw52Idq6a07Y4yxyXAbaRMHQk7u\n\
h9+59qA0u+ubwH9EAFqMYdqLQbSEGE/GYSi+2VNKE0YzZC8LU5J62G9is/9ctJpK\n\
RwIDAQAB\n\
-----END PUBLIC KEY-----\n";
    const RSA_ORACLE_SIGNED_STRING: &str = "(request-target): post /users/bob/inbox\nhost: neko.example\ndate: Mon, 21 Sep 2026 08:53:21 GMT\ndigest: SHA-256=NoWmF3S/Ultg02xVcgsZkPhruzzbiQmgtUgs4kJMsqs=";
    const RSA_ORACLE_SIGNATURE_B64: &str = "VRHwyUSRkmjD+yGLvxdBmAHvOJHo3Ll9jNrnABlZ8rAw7VH4MP8B6oT77Z0Kknul6NMad7kuKXlBMchYyE0dqkU4PrRy/bk7VYqCD7+Ugx5vXQO8GqIiEOMIVZk6k5sMXB0hDGqRsmB818VPGT2jT+LEfszu4sqYY7Cfw3/bPiT1Yf4UbLrne2Q0Hz9sv1G2y5rRhQN0bxVOhK1+FYk39v9cg73+kznkApDZazpUOVx23PujLTk+GGzcbLzczK/7sD+vZWcDit128iZH0FtpU7+cQt04AYITDXqeMEReqIwkeniy1PJbKNJFiV1cIAEW+fGyFCjrzIK1mwM94corEQ==";

    const ED25519_ORACLE_PUBLIC_KEY_MULTIBASE: &str =
        "z6Mkit1prV4UST7a2XKiD8AH3sB3d492bQVQrF2yHQBSWFeK";
    const ED25519_ORACLE_SIGNED_STRING: &str = "(request-target): post /users/bob/inbox\nhost: neko.example\ndate: Mon, 21 Sep 2026 08:53:21 GMT\ndigest: SHA-256=NoWmF3S/Ultg02xVcgsZkPhruzzbiQmgtUgs4kJMsqs=";
    const ED25519_ORACLE_SIGNATURE_B64: &str =
        "nHNlUBDlQCJ0DntDvZcZgeKQis+75B156SBJYxQuB5xgsMqCahFIyClfcreAItUCfEWc+oyZm31qM4YXd9HOCg==";

    #[test]
    fn verify_rsa_sha256_accepts_python_generated_signature() {
        let sig = BASE64.decode(RSA_ORACLE_SIGNATURE_B64).unwrap();
        assert!(verify_rsa_sha256(
            RSA_ORACLE_PUBLIC_KEY_PEM,
            RSA_ORACLE_SIGNED_STRING.as_bytes(),
            &sig,
        ));
    }

    #[test]
    fn verify_rsa_sha256_rejects_tampered_message() {
        let sig = BASE64.decode(RSA_ORACLE_SIGNATURE_B64).unwrap();
        assert!(!verify_rsa_sha256(
            RSA_ORACLE_PUBLIC_KEY_PEM,
            b"tampered message",
            &sig,
        ));
    }

    #[test]
    fn verify_ed25519_accepts_python_generated_signature() {
        let sig = BASE64.decode(ED25519_ORACLE_SIGNATURE_B64).unwrap();
        assert!(verify_ed25519(
            ED25519_ORACLE_PUBLIC_KEY_MULTIBASE,
            ED25519_ORACLE_SIGNED_STRING.as_bytes(),
            &sig,
        ));
    }

    #[test]
    fn verify_ed25519_rejects_tampered_message() {
        let sig = BASE64.decode(ED25519_ORACLE_SIGNATURE_B64).unwrap();
        assert!(!verify_ed25519(
            ED25519_ORACLE_PUBLIC_KEY_MULTIBASE,
            b"tampered message",
            &sig,
        ));
    }

    /// フルパイプライン(`parse_signature_header`→ヘッダー必須チェック→鮮度
    /// チェック→アルゴリズム判別→暗号検証)を通しで検証するため、
    /// オラクル値から実際に `Signature` ヘッダーを組み立てて確認する。
    fn build_signature_header(key_id: &str, algorithm: &str, signature_b64: &str) -> String {
        format!(
            r#"keyId="{key_id}",algorithm="{algorithm}",headers="(request-target) host date digest",signature="{signature_b64}""#
        )
    }

    #[test]
    fn is_fresh_date_accepts_current_gmt_formatted_date() {
        // RFC 2822 の obsolete zone名 "GMT" (Python の
        // `email.utils.format_datetime(usegmt=True)` が生成する形式)。
        // これをパースできないと実在するMastodon等からの署名済みリクエストを
        // 全て弾いてしまうため、明示的にテストする。
        let now_gmt = Utc::now().format("%a, %d %b %Y %H:%M:%S GMT").to_string();
        assert!(is_fresh_date(&now_gmt));
    }

    #[test]
    fn is_fresh_date_rejects_stale_date() {
        assert!(!is_fresh_date("Mon, 01 Jan 2001 00:00:00 GMT"));
    }

    #[test]
    fn is_fresh_date_rejects_unparseable_date() {
        assert!(!is_fresh_date("not-a-date"));
    }

    #[test]
    fn verify_signature_rejects_stale_date() {
        let sig_header = build_signature_header(
            "https://remote.example/users/alice#main-key",
            "rsa-sha256",
            RSA_ORACLE_SIGNATURE_B64,
        );
        let headers = headers_map(&[
            ("host", "neko.example"),
            // 恒久的に「12時間以上前」であり続ける日時。
            ("date", "Mon, 01 Jan 2001 00:00:00 GMT"),
            (
                "digest",
                "SHA-256=NoWmF3S/Ultg02xVcgsZkPhruzzbiQmgtUgs4kJMsqs=",
            ),
        ]);
        assert!(!verify_signature(
            RSA_ORACLE_PUBLIC_KEY_PEM,
            &sig_header,
            "POST",
            "/users/bob/inbox",
            &headers,
            Some("rsa-sha256"),
        ));
    }

    #[test]
    fn verify_signature_rejects_missing_required_params() {
        let headers = headers_map(&[("host", "neko.example"), ("date", "irrelevant")]);
        assert!(!verify_signature(
            RSA_ORACLE_PUBLIC_KEY_PEM,
            r#"algorithm="rsa-sha256""#,
            "POST",
            "/users/bob/inbox",
            &headers,
            None,
        ));
    }

    #[test]
    fn verify_signature_rejects_when_digest_not_signed_for_post() {
        let sig_header = build_signature_header(
            "https://remote.example/users/alice#main-key",
            "rsa-sha256",
            RSA_ORACLE_SIGNATURE_B64,
        )
        .replace(
            r#"headers="(request-target) host date digest""#,
            r#"headers="(request-target) host date""#,
        );
        let headers = headers_map(&[("host", "neko.example"), ("date", &Utc::now().to_rfc2822())]);
        assert!(!verify_signature(
            RSA_ORACLE_PUBLIC_KEY_PEM,
            &sig_header,
            "POST",
            "/users/bob/inbox",
            &headers,
            Some("rsa-sha256"),
        ));
    }

    #[test]
    fn verify_signature_rejects_ed25519_algorithm_with_rsa_key() {
        let sig_header = build_signature_header(
            "https://remote.example/users/alice#main-key",
            "ed25519",
            RSA_ORACLE_SIGNATURE_B64,
        );
        let headers = headers_map(&[
            ("host", "neko.example"),
            ("date", &Utc::now().to_rfc2822()),
            ("digest", "SHA-256=x"),
        ]);
        assert!(!verify_signature(
            RSA_ORACLE_PUBLIC_KEY_PEM, // RSA PEM, not multibase
            &sig_header,
            "POST",
            "/users/bob/inbox",
            &headers,
            None,
        ));
    }

    #[test]
    fn verify_signature_rejects_rsa_algorithm_with_ed25519_key() {
        let sig_header = build_signature_header(
            "https://remote.example/users/carol#ed25519-key",
            "rsa-sha256",
            ED25519_ORACLE_SIGNATURE_B64,
        );
        let headers = headers_map(&[
            ("host", "neko.example"),
            ("date", &Utc::now().to_rfc2822()),
            ("digest", "SHA-256=x"),
        ]);
        assert!(!verify_signature(
            ED25519_ORACLE_PUBLIC_KEY_MULTIBASE, // multibase, not RSA PEM
            &sig_header,
            "POST",
            "/users/bob/inbox",
            &headers,
            None,
        ));
    }

    #[test]
    fn verify_signature_rejects_unknown_algorithm() {
        let sig_header = build_signature_header(
            "https://remote.example/users/alice#main-key",
            "md5-nonsense",
            RSA_ORACLE_SIGNATURE_B64,
        );
        let headers = headers_map(&[
            ("host", "neko.example"),
            ("date", &Utc::now().to_rfc2822()),
            ("digest", "SHA-256=x"),
        ]);
        assert!(!verify_signature(
            RSA_ORACLE_PUBLIC_KEY_PEM,
            &sig_header,
            "POST",
            "/users/bob/inbox",
            &headers,
            None,
        ));
    }

    #[test]
    fn verify_signature_falls_back_to_hint_when_algorithm_is_hs2019() {
        // hs2019(RFC非依存の新方式表記)は algorithm_hint を尊重する。
        let sig_header = build_signature_header(
            "https://remote.example/users/alice#main-key",
            "hs2019",
            RSA_ORACLE_SIGNATURE_B64,
        );
        let headers = headers_map(&[
            ("host", "neko.example"),
            ("date", &Utc::now().to_rfc2822()),
            ("digest", "SHA-256=x"),
        ]);
        assert!(!verify_signature(
            RSA_ORACLE_PUBLIC_KEY_PEM,
            &sig_header,
            "POST",
            "/users/bob/inbox",
            &headers,
            Some("ed25519"), // RSA鍵なのにed25519ヒントを渡すと鍵種別不一致で拒否
        ));
    }

    /// 個々の分岐(鮮度・アルゴリズム判別・暗号検証)は上のテストで固定
    /// オラクル値を使って検証済みだが、それらを繋ぐ配線自体
    /// (`(request-target)`の組み立て・ヘッダー突き合わせ・digest一致)が
    /// 壊れていないことを、実行時に鍵生成・署名までRust側で完結させる
    /// ラウンドトリップで確認する。Python オラクルとは独立した検証経路。
    #[test]
    fn verify_signature_full_pipeline_round_trip_with_freshly_generated_rsa_key() {
        use rand::rngs::OsRng;
        use rsa::pkcs8::EncodePublicKey;
        use rsa::RsaPrivateKey;

        let private_key = RsaPrivateKey::new(&mut OsRng, 2048).expect("keygen");
        let public_key = RsaPublicKey::from(&private_key);
        let public_key_pem = public_key
            .to_public_key_pem(rsa::pkcs8::LineEnding::LF)
            .expect("encode pem");

        let body = b"{\"type\":\"Create\"}";
        let digest_value = format!("SHA-256={}", BASE64.encode(Sha256::digest(body)));
        let date = Utc::now().to_rfc2822();
        let signed_string = format!(
            "(request-target): post /users/bob/inbox\nhost: neko.example\ndate: {date}\ndigest: {digest_value}"
        );
        let hashed = Sha256::digest(signed_string.as_bytes());
        let signature = private_key
            .sign(Pkcs1v15Sign::new::<Sha256>(), &hashed)
            .expect("sign");
        let signature_b64 = BASE64.encode(signature);

        let sig_header = build_signature_header(
            "https://remote.example/users/alice#main-key",
            "rsa-sha256",
            &signature_b64,
        );
        let headers = headers_map(&[
            ("host", "neko.example"),
            ("date", &date),
            ("digest", &digest_value),
        ]);

        assert!(verify_signature(
            &public_key_pem,
            &sig_header,
            "POST",
            "/users/bob/inbox",
            &headers,
            Some("rsa-sha256"),
        ));

        // 本文が改ざんされればdigestが一致しなくなり、署名対象文字列も
        // 変わらないため検証は失敗する。
        assert!(!verify_signature(
            &public_key_pem,
            &sig_header,
            "POST",
            "/users/bob/inbox",
            &headers_map(&[
                ("host", "neko.example"),
                ("date", &date),
                ("digest", "SHA-256=dGFtcGVyZWQ="),
            ]),
            Some("rsa-sha256"),
        ));
    }
}
