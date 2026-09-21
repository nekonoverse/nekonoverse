//! `app/services/totp_service.py` を移植したもの。RFC 4226 (HOTP) / RFC 6238 (TOTP)、
//! Fernet対称暗号化によるsecretの保管、リカバリーコードのbcryptハッシュ化、
//! ユーザー単位のブルートフォースロックアウト(Valkey)を提供する。
//!
//! `encrypt_secret`/`decrypt_secret` はPython版と全く同じ鍵導出規則
//! (PBKDF2-HMAC-SHA256 600,000回、ソルト`nekonoverse-totp-encryption`から導出した
//! Fernetキー、失敗時はSHA-256直接導出のレガシーキーへフォールバック)を踏襲する。
//! 既存ユーザーのDB上の暗号化済みsecretをRust側が復号する必要があるため、
//! Pythonの`cryptography.fernet.Fernet`が生成したトークンとのバイト互換性を
//! 実際にPython側で生成したオラクル値を使ったテストで検証している。

use base64::engine::general_purpose::URL_SAFE;
use base64::Engine;
use hmac::{Hmac, Mac};
use pbkdf2::pbkdf2_hmac;
use rand::RngCore;
use redis::AsyncCommands;
use sha1::Sha1;
use sha2::{Digest, Sha256};
use uuid::Uuid;

use crate::error::AppError;

const TOTP_STEP_SECONDS: i64 = 30;
const TOTP_VALID_WINDOW: i64 = 1;
/// `app.services.totp_service`のPBKDF2イテレーション回数のデフォルト
/// (Python版と同一の60万回)。`config.rs`の`Config::totp_pbkdf2_iterations`の
/// デフォルト値として参照する。
pub const PBKDF2_ITERATIONS_DEFAULT: u32 = 600_000;
const PBKDF2_SALT: &[u8] = b"nekonoverse-totp-encryption";

/// `app.services.totp_service.TOTP_USER_MAX_FAILURES`/`TOTP_USER_LOCKOUT_TTL` と同一。
const TOTP_USER_MAX_FAILURES: i64 = 10;
const TOTP_USER_LOCKOUT_TTL: i64 = 900;

fn user_failure_key(user_id: Uuid) -> String {
    format!("totp_failures:user:{user_id}")
}

/// `app.services.totp_service.is_totp_locked` を移植したもの。
pub async fn is_totp_locked(
    redis: &redis::aio::ConnectionManager,
    user_id: Uuid,
) -> Result<bool, AppError> {
    let mut redis = redis.clone();
    let failures: Option<i64> = redis.get(user_failure_key(user_id)).await?;
    Ok(failures.is_some_and(|f| f >= TOTP_USER_MAX_FAILURES))
}

/// `app.services.totp_service.record_totp_failure` を移植したもの。
/// `EXPIRE ... NX` で「最初の失敗からの固定ウィンドウ」を再現する
/// (Python版の`valkey.expire(key, TTL, nx=True)`と同じ意図)。
pub async fn record_totp_failure(
    redis: &redis::aio::ConnectionManager,
    user_id: Uuid,
) -> Result<(), AppError> {
    let mut redis = redis.clone();
    let key = user_failure_key(user_id);
    let _: i64 = redis.incr(&key, 1).await?;
    let _: () = redis::cmd("EXPIRE")
        .arg(&key)
        .arg(TOTP_USER_LOCKOUT_TTL)
        .arg("NX")
        .query_async(&mut redis)
        .await?;
    Ok(())
}

/// `app.services.totp_service.clear_totp_failures` を移植したもの。
pub async fn clear_totp_failures(
    redis: &redis::aio::ConnectionManager,
    user_id: Uuid,
) -> Result<(), AppError> {
    let mut redis = redis.clone();
    let _: i64 = redis.del(user_failure_key(user_id)).await?;
    Ok(())
}

/// `app.services.totp_service.advance_last_totp_counter` を移植したもの。
/// 単調増加 CAS — 別リクエストが先に同等以上の counter を記録していたら
/// `false` を返す (リプレイ防止の競合解決)。
pub async fn advance_last_totp_counter(
    db: &sqlx::PgPool,
    user_id: Uuid,
    new_counter: i64,
) -> Result<bool, AppError> {
    let result = sqlx::query(
        "UPDATE users SET last_totp_counter = $1 \
         WHERE id = $2 AND (last_totp_counter IS NULL OR last_totp_counter < $1)",
    )
    .bind(new_counter)
    .bind(user_id)
    .execute(db)
    .await?;
    Ok(result.rows_affected() > 0)
}

fn derive_fernet_key(secret_key: &str, iterations: u32) -> String {
    let mut dk = [0u8; 32];
    pbkdf2_hmac::<Sha256>(secret_key.as_bytes(), PBKDF2_SALT, iterations, &mut dk);
    URL_SAFE.encode(dk)
}

fn derive_legacy_fernet_key(secret_key: &str) -> String {
    let digest = Sha256::digest(secret_key.as_bytes());
    URL_SAFE.encode(digest)
}

/// `app.services.totp_service.encrypt_secret` を移植したもの。`iterations`は
/// 本番では常に`PBKDF2_ITERATIONS`(Python版と同一の60万回)を渡す
/// (`Config::totp_pbkdf2_iterations`参照)。デバッグビルドではRustCrypto系の
/// PBKDF2実装が最適化ビルドに比べ大幅に低速なため、結合テストでは
/// 環境変数で短縮したイテレーション回数を渡せるようにしてある
/// (`bcrypt_cost`と同じ方針)。
pub fn encrypt_secret(
    secret_key: &str,
    plaintext: &str,
    iterations: u32,
) -> Result<String, AppError> {
    let key = derive_fernet_key(secret_key, iterations);
    let fernet = fernet::Fernet::new(&key).ok_or_else(|| {
        AppError::new(
            axum::http::StatusCode::INTERNAL_SERVER_ERROR,
            "Internal server error",
        )
    })?;
    Ok(fernet.encrypt(plaintext.as_bytes()))
}

/// `app.services.totp_service.decrypt_secret` を移植したもの。
pub fn decrypt_secret(
    secret_key: &str,
    ciphertext: &str,
    iterations: u32,
) -> Result<String, AppError> {
    let internal_error = || {
        AppError::new(
            axum::http::StatusCode::INTERNAL_SERVER_ERROR,
            "Internal server error",
        )
    };

    let key = derive_fernet_key(secret_key, iterations);
    if let Some(fernet) = fernet::Fernet::new(&key) {
        if let Ok(bytes) = fernet.decrypt(ciphertext) {
            if let Ok(s) = String::from_utf8(bytes) {
                return Ok(s);
            }
        }
    }

    let legacy_key = derive_legacy_fernet_key(secret_key);
    let fernet = fernet::Fernet::new(&legacy_key).ok_or_else(internal_error)?;
    let bytes = fernet.decrypt(ciphertext).map_err(|_| internal_error())?;
    String::from_utf8(bytes).map_err(|_| internal_error())
}

const BASE32_ALPHABET: &[u8] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";

/// `base64.b32decode(secret, casefold=True)` 相当 (RFC 4648 base32、パディング寛容)。
fn base32_decode(input: &str) -> Option<Vec<u8>> {
    let cleaned: Vec<u8> = input
        .trim()
        .to_ascii_uppercase()
        .bytes()
        .filter(|b| *b != b'=')
        .collect();
    if cleaned.is_empty() {
        return None;
    }
    let mut bits: u64 = 0;
    let mut bit_count = 0u32;
    let mut out = Vec::new();
    for c in cleaned {
        let value = BASE32_ALPHABET.iter().position(|&a| a == c)? as u64;
        bits = (bits << 5) | value;
        bit_count += 5;
        if bit_count >= 8 {
            bit_count -= 8;
            out.push((bits >> bit_count) as u8);
        }
    }
    Some(out)
}

type HmacSha1 = Hmac<Sha1>;

/// RFC 4226 HOTP。`pyotp.HOTP(secret).at(counter)` を移植したもの。`pub`にして
/// あるのは統合テスト(`tests/auth.rs`)が`totp_setup`で発行されたsecretから
/// 有効なコードを生成するために必要なため(`hmac_sig::media_proxy_url`を
/// テストが直接呼ぶのと同じ既存の方針)。
pub fn hotp_at(secret: &str, counter: i64) -> Option<String> {
    let key = base32_decode(secret)?;
    let mut mac = HmacSha1::new_from_slice(&key).ok()?;
    mac.update(&counter.to_be_bytes());
    let digest = mac.finalize().into_bytes();

    let offset = (digest[19] & 0x0f) as usize;
    let binary = ((u32::from(digest[offset]) & 0x7f) << 24)
        | (u32::from(digest[offset + 1]) << 16)
        | (u32::from(digest[offset + 2]) << 8)
        | u32::from(digest[offset + 3]);
    let otp = binary % 1_000_000;
    Some(format!("{otp:06}"))
}

/// `secrets.compare_digest` 相当の定数時間文字列比較。
fn constant_time_eq(a: &str, b: &str) -> bool {
    if a.len() != b.len() {
        return false;
    }
    let mut diff = 0u8;
    for (x, y) in a.bytes().zip(b.bytes()) {
        diff |= x ^ y;
    }
    diff == 0
}

/// `app.services.totp_service.current_time_step` を移植したもの。
pub fn current_time_step(now: Option<i64>) -> i64 {
    let now = now.unwrap_or_else(|| chrono::Utc::now().timestamp());
    now.div_euclid(TOTP_STEP_SECONDS)
}

/// `app.services.totp_service.verify_totp_code_with_counter` を移植したもの。
pub fn verify_totp_code_with_counter(
    secret: &str,
    code: &str,
    last_counter: Option<i64>,
    now: Option<i64>,
) -> Option<i64> {
    let current = current_time_step(now);
    let candidate: String = code.trim().chars().filter(|c| *c != ' ').collect();
    if candidate.is_empty() {
        return None;
    }

    let mut offsets = vec![0i64];
    for i in 1..=TOTP_VALID_WINDOW {
        offsets.push(-i);
        offsets.push(i);
    }

    let mut matched: Option<i64> = None;
    for offset in offsets {
        let counter = current + offset;
        if let Some(expected) = hotp_at(secret, counter) {
            if constant_time_eq(&expected, &candidate) {
                matched = Some(counter);
                break;
            }
        }
    }

    let matched = matched?;
    if let Some(last) = last_counter {
        if matched <= last {
            return None;
        }
    }
    Some(matched)
}

/// `pyotp.random_base32()` と同じ文字集合・長さ(32文字)で新規secretを生成する。
/// Python版は`random.choice`(非暗号論的PRNG)を使うが、こちらは新規secretの
/// 生成にのみ使われる値であり既存データとの互換性を要さないため、
/// `rand::thread_rng`(ChaCha ベースの暗号論的PRNG)を使う安全側の改善とする。
pub fn generate_totp_secret() -> String {
    let mut rng = rand::thread_rng();
    (0..32)
        .map(|_| {
            let idx = (rng.next_u32() as usize) % BASE32_ALPHABET.len();
            BASE32_ALPHABET[idx] as char
        })
        .collect()
}

/// `pyotp.utils.build_uri`(`algorithm`/`digits`/`period`が全てデフォルト値の場合の
/// 経路のみ)を移植したもの。`urllib.parse.quote`/`urlencode`+`+`→`%20`置換を
/// 手動実装で再現する(値に`/`を含み得ないユーザー名/issuer文字列のみが入力の
/// ため、`quote`のsafe='/'との差異は生じない)。
fn percent_encode(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for b in s.bytes() {
        match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'.' | b'_' | b'~' => {
                out.push(b as char)
            }
            b' ' => out.push_str("%20"),
            _ => out.push_str(&format!("%{b:02X}")),
        }
    }
    out
}

/// `app.services.totp_service.generate_provisioning_uri` を移植したもの。
pub fn generate_provisioning_uri(secret: &str, username: &str, issuer: &str) -> String {
    let label = format!("{}:{}", percent_encode(issuer), percent_encode(username));
    format!(
        "otpauth://totp/{label}?secret={secret}&issuer={}",
        percent_encode(issuer)
    )
}

const RECOVERY_CODE_ALPHABET: &[u8] = b"abcdefghijklmnopqrstuvwxyz0123456789";

/// `app.services.totp_service.generate_recovery_codes` を移植したもの。
pub fn generate_recovery_codes() -> Vec<String> {
    let mut rng = rand::thread_rng();
    let random_part = |rng: &mut rand::rngs::ThreadRng| -> String {
        (0..5)
            .map(|_| {
                let idx = (rng.next_u32() as usize) % RECOVERY_CODE_ALPHABET.len();
                RECOVERY_CODE_ALPHABET[idx] as char
            })
            .collect::<String>()
    };
    (0..8)
        .map(|_| format!("{}-{}", random_part(&mut rng), random_part(&mut rng)))
        .collect()
}

/// `app.services.totp_service.hash_recovery_codes` を移植したもの。
pub fn hash_recovery_codes(codes: &[String], cost: u32) -> Result<Vec<String>, AppError> {
    codes
        .iter()
        .map(|c| {
            bcrypt::hash(c, cost).map_err(|_| {
                AppError::new(
                    axum::http::StatusCode::INTERNAL_SERVER_ERROR,
                    "Internal server error",
                )
            })
        })
        .collect()
}

/// `app.services.totp_service.verify_recovery_code` を移植したもの。
/// タイミング攻撃対策のため、一致が見つかった後も残り全件のbcrypt照合を続行する。
pub fn verify_recovery_code(code: &str, hashed_codes: &[String]) -> (bool, Vec<String>) {
    let mut matched_index: Option<usize> = None;
    for (i, hashed) in hashed_codes.iter().enumerate() {
        if bcrypt::verify(code, hashed).unwrap_or(false) && matched_index.is_none() {
            matched_index = Some(i);
        }
    }
    match matched_index {
        Some(i) => {
            let mut remaining = hashed_codes.to_vec();
            remaining.remove(i);
            (true, remaining)
        }
        None => (false, hashed_codes.to_vec()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // オラクル値: `pyotp.HOTP("JBSWY3DPEHPK3PXP").at(counter)` の実行結果。
    #[test]
    fn hotp_at_matches_python_oracle() {
        assert_eq!(hotp_at("JBSWY3DPEHPK3PXP", 0).as_deref(), Some("282760"));
        assert_eq!(hotp_at("JBSWY3DPEHPK3PXP", 1).as_deref(), Some("996554"));
        assert_eq!(
            hotp_at("JBSWY3DPEHPK3PXP", 999_999).as_deref(),
            Some("573225")
        );
        assert_eq!(
            hotp_at("JBSWY3DPEHPK3PXP", 1_234_567).as_deref(),
            Some("453783")
        );
    }

    #[test]
    fn verify_totp_code_with_counter_accepts_current_window() {
        let now = 12345 * TOTP_STEP_SECONDS;
        let current = now / TOTP_STEP_SECONDS;
        let code = hotp_at("JBSWY3DPEHPK3PXP", current).unwrap();
        let matched = verify_totp_code_with_counter("JBSWY3DPEHPK3PXP", &code, None, Some(now));
        assert_eq!(matched, Some(current));
    }

    #[test]
    fn verify_totp_code_with_counter_accepts_adjacent_window() {
        let now = 12345 * TOTP_STEP_SECONDS;
        let current = now / TOTP_STEP_SECONDS;
        let code = hotp_at("JBSWY3DPEHPK3PXP", current + 1).unwrap();
        let matched = verify_totp_code_with_counter("JBSWY3DPEHPK3PXP", &code, None, Some(now));
        assert_eq!(matched, Some(current + 1));
    }

    #[test]
    fn verify_totp_code_with_counter_rejects_out_of_window() {
        let now = 12345 * TOTP_STEP_SECONDS;
        let current = now / TOTP_STEP_SECONDS;
        let code = hotp_at("JBSWY3DPEHPK3PXP", current + 2).unwrap();
        let matched = verify_totp_code_with_counter("JBSWY3DPEHPK3PXP", &code, None, Some(now));
        assert_eq!(matched, None);
    }

    #[test]
    fn verify_totp_code_with_counter_rejects_replayed_counter() {
        let now = 12345 * TOTP_STEP_SECONDS;
        let current = now / TOTP_STEP_SECONDS;
        let code = hotp_at("JBSWY3DPEHPK3PXP", current).unwrap();
        let matched =
            verify_totp_code_with_counter("JBSWY3DPEHPK3PXP", &code, Some(current), Some(now));
        assert_eq!(matched, None);
    }

    #[test]
    fn verify_totp_code_with_counter_rejects_empty_code() {
        let now = 12345 * TOTP_STEP_SECONDS;
        assert_eq!(
            verify_totp_code_with_counter("JBSWY3DPEHPK3PXP", "  ", None, Some(now)),
            None
        );
    }

    // オラクル値: `hashlib.pbkdf2_hmac("sha256", "test-secret-key-for-oracle-fixture-do-not-use-in-prod".encode(),
    // b"nekonoverse-totp-encryption", iterations=600_000)` を
    // `base64.urlsafe_b64encode` したもの。
    #[test]
    fn derive_fernet_key_matches_python_oracle() {
        let key = derive_fernet_key(
            "test-secret-key-for-oracle-fixture-do-not-use-in-prod",
            PBKDF2_ITERATIONS_DEFAULT,
        );
        assert_eq!(key, "1SdCehztNY5a-xuU3zHGi0RBeMZ5B2wWOJO0ERwmeYo=");
    }

    #[test]
    fn derive_legacy_fernet_key_matches_python_oracle() {
        let key = derive_legacy_fernet_key("test-secret-key-for-oracle-fixture-do-not-use-in-prod");
        assert_eq!(key, "mooIMfLfl8i1Ft9fpj77p1mZCdq0rgyb2JP9-BjgpS8=");
    }

    // オラクル値: 上記キーで実際にPythonの`cryptography.fernet.Fernet`が生成した
    // トークン。`ttl`を指定しない`decrypt()`は有効期限を検証しないため、
    // このトークンはいつテストを実行しても復号に成功する。
    #[test]
    fn decrypt_secret_matches_python_generated_token() {
        let secret_key = "test-secret-key-for-oracle-fixture-do-not-use-in-prod";
        let token = "gAAAAABqsWqkvq5BVGGlEIwxjjaC-8IUPiM84kqt6MqPOfybjBRvFx08mSeGE1p54FJMhjErosrrBdBN_d5RLGLnkrjGtgpqAg==";
        assert_eq!(
            decrypt_secret(secret_key, token, PBKDF2_ITERATIONS_DEFAULT).unwrap(),
            "MYSECRETVALUE"
        );
    }

    #[test]
    fn decrypt_secret_falls_back_to_legacy_key() {
        let secret_key = "test-secret-key-for-oracle-fixture-do-not-use-in-prod";
        let legacy_token = "gAAAAABqsWqk-IWvmWfR09jCruuaG2lEzD77bLjHugqPcILTV0lODmpTxQPpRsTLC-G5sDFq5YckQtBvp_wkkFzZDIax4WR9gA==";
        assert_eq!(
            decrypt_secret(secret_key, legacy_token, PBKDF2_ITERATIONS_DEFAULT).unwrap(),
            "LEGACYVALUE"
        );
    }

    #[test]
    fn encrypt_then_decrypt_round_trips() {
        // 相互運用性ではなくRust内部でのラウンドトリップ整合性のみを見る
        // テストのため、実行時間短縮のため低イテレーション回数を使う。
        let secret_key = "another-secret-key";
        let token = encrypt_secret(secret_key, "TOPSECRET", 100).unwrap();
        assert_eq!(
            decrypt_secret(secret_key, &token, 100).unwrap(),
            "TOPSECRET"
        );
    }

    #[test]
    fn generate_provisioning_uri_matches_python_oracle() {
        let uri =
            generate_provisioning_uri("JBSWY3DPEHPK3PXP", "alice", "Nekonoverse (example.com)");
        assert_eq!(
            uri,
            "otpauth://totp/Nekonoverse%20%28example.com%29:alice?secret=JBSWY3DPEHPK3PXP&issuer=Nekonoverse%20%28example.com%29"
        );
    }

    #[test]
    fn generate_totp_secret_has_expected_length_and_alphabet() {
        let secret = generate_totp_secret();
        assert_eq!(secret.len(), 32);
        assert!(secret.bytes().all(|b| BASE32_ALPHABET.contains(&b)));
    }

    #[test]
    fn generate_recovery_codes_has_expected_shape() {
        let codes = generate_recovery_codes();
        assert_eq!(codes.len(), 8);
        for code in &codes {
            let parts: Vec<&str> = code.split('-').collect();
            assert_eq!(parts.len(), 2);
            assert_eq!(parts[0].len(), 5);
            assert_eq!(parts[1].len(), 5);
        }
        // 重複が事実上起こらないことの簡易確認 (暗号論的RNGを使っている証拠)。
        let unique: std::collections::HashSet<&String> = codes.iter().collect();
        assert_eq!(unique.len(), codes.len());
    }

    #[test]
    fn hash_and_verify_recovery_code_roundtrip() {
        let codes = vec!["abcde-12345".to_string(), "fghij-67890".to_string()];
        // bcryptの最小コスト(4)。テストの実行時間短縮のため(本番は`bcrypt_cost`
        // 設定値、デフォルト`bcrypt::DEFAULT_COST`)。
        let hashed = hash_recovery_codes(&codes, 4).unwrap();
        let (ok, remaining) = verify_recovery_code("abcde-12345", &hashed);
        assert!(ok);
        assert_eq!(remaining.len(), 1);
        assert_eq!(remaining[0], hashed[1]);

        let (ok2, remaining2) = verify_recovery_code("abcde-12345", &hashed);
        // 元のリスト(2件)に対する再照合はまだ成功する(消費は呼び出し側がDB更新で行う)。
        assert!(ok2);
        assert_eq!(remaining2.len(), 1);

        let (ok3, remaining3) = verify_recovery_code("wrong-code12", &hashed);
        assert!(!ok3);
        assert_eq!(remaining3.len(), 2);
    }

    // オラクル値: `bcrypt.hashpw(b"correcthorsebatterystaple", bcrypt.gensalt())`
    // (Python版のパスワードハッシュ/リカバリーコードハッシュと同じ`$2b$`形式)。
    #[test]
    fn bcrypt_verify_accepts_python_generated_hash() {
        let hash = "$2b$12$n5jJ0zP4gVbOKAKbR/6f1.InikvXPcFXa7oSiH.AOG57UoIY6H8bS";
        assert!(bcrypt::verify("correcthorsebatterystaple", hash).unwrap());
        assert!(!bcrypt::verify("wrongpassword", hash).unwrap());
    }
}
