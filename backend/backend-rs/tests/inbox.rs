//! `routes/inbox.rs`(H-4/H-5・Digest/HTTP Signature検証・鍵所有者一致検証)と
//! `inbox.rs`(Follow/Accept/Reject/Block/Delete/Flag/Undo(Follow/Block))の
//! 結合テスト。`tests/remote_actor.rs`の`seed_signing_user`と同じ理由で、
//! 「リモートから届いた」ことを模すために実際にパース可能なRSA鍵ペアで
//! リクエストを署名する。署名対象のactorは`last_fetched_at = now()`で
//! シードするため`get_actor_public_key`がキャッシュヒットし、
//! `fetch_remote_actor`のネットワークフェッチ経路(wiremock)を経由しない。

use axum::body::Body;
use axum::http::{Request, StatusCode};
use nekonoverse_backend_rs::http_signature::sign_request;
use rsa::pkcs8::{EncodePrivateKey, EncodePublicKey, LineEnding};
use rsa::RsaPrivateKey;
use serde_json::{json, Value};
use sqlx::PgPool;
use tower::ServiceExt;
use uuid::Uuid;

mod common;
use common::{seed_follow, seed_local_actor, seed_note, seed_user_block, test_app_with_db};

/// リモートactorを実鍵付きでシードする。`last_fetched_at`を`now()`にする
/// ことで`fetch_remote_actor`の1時間キャッシュが即座にヒットし、署名検証の
/// ためだけにネットワークフェッチが発生しないようにする。
async fn seed_remote_signing_actor(
    db: &PgPool,
    username: &str,
    domain: &str,
) -> (Uuid, String, String) {
    let mut rng = rand::thread_rng();
    let private_key = RsaPrivateKey::new(&mut rng, 2048).unwrap();
    let private_pem = private_key
        .to_pkcs8_pem(LineEnding::LF)
        .unwrap()
        .to_string();
    let public_pem = rsa::RsaPublicKey::from(&private_key)
        .to_public_key_pem(LineEnding::LF)
        .unwrap();

    let id = Uuid::new_v4();
    let ap_id = format!("https://{domain}/users/{username}");
    let inbox_url = format!("{ap_id}/inbox");
    sqlx::query(
        r#"
        INSERT INTO actors (
            id, ap_id, type, username, domain, inbox_url, public_key_pem,
            is_cat, manually_approves_followers, discoverable, is_bot,
            require_signin_to_view, last_fetched_at, created_at, updated_at
        ) VALUES (
            $1, $2, 'Person', $3, $4, $5, $6,
            false, false, true, false,
            false, now(), now(), now()
        )
        "#,
    )
    .bind(id)
    .bind(&ap_id)
    .bind(username)
    .bind(domain)
    .bind(&inbox_url)
    .bind(&public_pem)
    .execute(db)
    .await
    .expect("failed to seed remote signing actor");

    (id, private_pem, ap_id)
}

async fn set_manually_approves(db: &PgPool, actor_id: Uuid, value: bool) {
    sqlx::query("UPDATE actors SET manually_approves_followers = $1 WHERE id = $2")
        .bind(value)
        .bind(actor_id)
        .execute(db)
        .await
        .unwrap();
}

/// テストごとに一意な`X-Real-IP`を振り、Valkeyのinboxレート制限カウンタ
/// (`inbox_rate:{ip}`)が並行実行中の他テストと衝突しないようにする。
fn unique_ip() -> String {
    // 3オクテット分(約1600万通り)のエントロピーを持たせ、レート制限テストが
    // 200リクエスト分専有する`ip`と他テストの`unique_ip()`呼び出しが衝突する
    // 確率を無視できる水準にする(全テストが同一Valkeyインスタンスを共有し、
    // `#[tokio::test]`は同一プロセス内で並行実行されるため)。
    format!(
        "10.{}.{}.{}",
        rand::random::<u8>(),
        rand::random::<u8>(),
        rand::random::<u8>()
    )
}

/// `sign_request`で実際に署名した`POST`リクエストを組み立てる。署名対象URLの
/// ホスト部分がそのまま`Host`ヘッダーとして送られる(値自体はルーティングに
/// 使われないため任意の文字列でよいが、署名文字列との整合性のため
/// `sign_request`が計算した値をそのまま使う)。
fn build_signed_request(
    path: &str,
    private_key_pem: &str,
    key_id: &str,
    body: &Value,
) -> Request<Body> {
    let body_bytes = serde_json::to_vec(body).unwrap();
    let url = format!("https://neko.example{path}");
    let headers = sign_request(private_key_pem, key_id, "POST", &url, Some(&body_bytes))
        .expect("failed to sign test request");

    let mut builder = Request::builder()
        .method("POST")
        .uri(path)
        .header("content-type", "application/activity+json")
        .header("x-real-ip", unique_ip());
    for (name, value) in &headers {
        builder = builder.header(name.as_str(), value.as_str());
    }
    builder.body(Body::from(body_bytes)).unwrap()
}

fn follow_activity(id: &str, actor: &str, object: &str) -> Value {
    json!({ "id": id, "type": "Follow", "actor": actor, "object": object })
}

/// `Digest: SHA-256=<base64>` ヘッダー値を計算する。署名検証より前段の
/// Digest検証だけを先に通過させ、その先(Signatureヘッダー欠如など)を
/// 狙って検証したいテストで使う。
fn digest_header_for(body: &[u8]) -> String {
    use base64::Engine;
    use sha2::Digest as _;
    format!(
        "SHA-256={}",
        base64::engine::general_purpose::STANDARD.encode(sha2::Sha256::digest(body))
    )
}

#[tokio::test]
async fn inbox_follow_auto_accepts_and_enqueues_accept_delivery() {
    let (app, db) = test_app_with_db().await;
    let target_username = format!("target{}", Uuid::new_v4().simple());
    let target_id = seed_local_actor(&db, &target_username).await;

    let remote_username = format!("remote{}", Uuid::new_v4().simple());
    let (follower_id, private_pem, follower_ap_id) =
        seed_remote_signing_actor(&db, &remote_username, "remote.example").await;

    let target_ap_id = format!("https://localhost/users/{target_username}");
    let activity_id = format!("https://remote.example/activities/{}", Uuid::new_v4());
    let body = follow_activity(&activity_id, &follower_ap_id, &target_ap_id);
    let key_id = format!("{follower_ap_id}#main-key");

    let req = build_signed_request(
        &format!("/users/{target_username}/inbox"),
        &private_pem,
        &key_id,
        &body,
    );
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::ACCEPTED);

    let accepted: bool = sqlx::query_scalar(
        "SELECT accepted FROM followers WHERE follower_id = $1 AND following_id = $2",
    )
    .bind(follower_id)
    .bind(target_id)
    .fetch_one(&db)
    .await
    .unwrap();
    assert!(accepted);

    let notif_type: String = sqlx::query_scalar(
        "SELECT type FROM notifications WHERE recipient_id = $1 AND sender_id = $2",
    )
    .bind(target_id)
    .bind(follower_id)
    .fetch_one(&db)
    .await
    .unwrap();
    assert_eq!(notif_type, "follow");

    let delivery_payload: sqlx::types::Json<Value> = sqlx::query_scalar(
        "SELECT payload FROM delivery_queue WHERE actor_id = $1 AND target_inbox_url = $2",
    )
    .bind(target_id)
    .bind(format!("{follower_ap_id}/inbox"))
    .fetch_one(&db)
    .await
    .unwrap();
    assert_eq!(delivery_payload.0["type"], "Accept");
}

#[tokio::test]
async fn inbox_follow_stays_pending_when_target_manually_approves() {
    let (app, db) = test_app_with_db().await;
    let target_username = format!("target{}", Uuid::new_v4().simple());
    let target_id = seed_local_actor(&db, &target_username).await;
    set_manually_approves(&db, target_id, true).await;

    let remote_username = format!("remote{}", Uuid::new_v4().simple());
    let (follower_id, private_pem, follower_ap_id) =
        seed_remote_signing_actor(&db, &remote_username, "remote.example").await;

    let target_ap_id = format!("https://localhost/users/{target_username}");
    let activity_id = format!("https://remote.example/activities/{}", Uuid::new_v4());
    let body = follow_activity(&activity_id, &follower_ap_id, &target_ap_id);
    let key_id = format!("{follower_ap_id}#main-key");

    let req = build_signed_request("/inbox", &private_pem, &key_id, &body);
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::ACCEPTED);

    let accepted: bool = sqlx::query_scalar(
        "SELECT accepted FROM followers WHERE follower_id = $1 AND following_id = $2",
    )
    .bind(follower_id)
    .bind(target_id)
    .fetch_one(&db)
    .await
    .unwrap();
    assert!(!accepted);

    let notif_type: String = sqlx::query_scalar(
        "SELECT type FROM notifications WHERE recipient_id = $1 AND sender_id = $2",
    )
    .bind(target_id)
    .bind(follower_id)
    .fetch_one(&db)
    .await
    .unwrap();
    assert_eq!(notif_type, "follow_request");

    let delivery_count: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM delivery_queue WHERE actor_id = $1")
            .bind(target_id)
            .fetch_one(&db)
            .await
            .unwrap();
    assert_eq!(delivery_count, 0);
}

#[tokio::test]
async fn inbox_follow_rejected_when_target_blocks_follower() {
    let (app, db) = test_app_with_db().await;
    let target_username = format!("target{}", Uuid::new_v4().simple());
    let target_id = seed_local_actor(&db, &target_username).await;

    let remote_username = format!("remote{}", Uuid::new_v4().simple());
    let (follower_id, private_pem, follower_ap_id) =
        seed_remote_signing_actor(&db, &remote_username, "remote.example").await;

    seed_user_block(&db, target_id, follower_id).await;

    let target_ap_id = format!("https://localhost/users/{target_username}");
    let activity_id = format!("https://remote.example/activities/{}", Uuid::new_v4());
    let body = follow_activity(&activity_id, &follower_ap_id, &target_ap_id);
    let key_id = format!("{follower_ap_id}#main-key");

    let req = build_signed_request("/inbox", &private_pem, &key_id, &body);
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::ACCEPTED);

    let follow_count: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM followers WHERE follower_id = $1 AND following_id = $2",
    )
    .bind(follower_id)
    .bind(target_id)
    .fetch_one(&db)
    .await
    .unwrap();
    assert_eq!(follow_count, 0);

    let delivery_payload: sqlx::types::Json<Value> =
        sqlx::query_scalar("SELECT payload FROM delivery_queue WHERE actor_id = $1")
            .bind(target_id)
            .fetch_one(&db)
            .await
            .unwrap();
    assert_eq!(delivery_payload.0["type"], "Reject");
}

#[tokio::test]
async fn inbox_deduplicates_activity_by_id() {
    let (app, db) = test_app_with_db().await;
    let target_username = format!("target{}", Uuid::new_v4().simple());
    let target_id = seed_local_actor(&db, &target_username).await;

    let remote_username = format!("remote{}", Uuid::new_v4().simple());
    let (follower_id, private_pem, follower_ap_id) =
        seed_remote_signing_actor(&db, &remote_username, "remote.example").await;

    let target_ap_id = format!("https://localhost/users/{target_username}");
    let activity_id = format!("https://remote.example/activities/{}", Uuid::new_v4());
    let body = follow_activity(&activity_id, &follower_ap_id, &target_ap_id);
    let key_id = format!("{follower_ap_id}#main-key");

    for _ in 0..2 {
        let req = build_signed_request("/inbox", &private_pem, &key_id, &body);
        let resp = app.clone().oneshot(req).await.unwrap();
        assert_eq!(resp.status(), StatusCode::ACCEPTED);
    }

    let follow_count: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM followers WHERE follower_id = $1 AND following_id = $2",
    )
    .bind(follower_id)
    .bind(target_id)
    .fetch_one(&db)
    .await
    .unwrap();
    assert_eq!(follow_count, 1);
}

#[tokio::test]
async fn inbox_accept_marks_follow_as_accepted() {
    let (app, db) = test_app_with_db().await;
    let local_username = format!("local{}", Uuid::new_v4().simple());
    let local_id = seed_local_actor(&db, &local_username).await;
    let local_ap_id = format!("https://localhost/users/{local_username}");

    let remote_username = format!("remote{}", Uuid::new_v4().simple());
    let (remote_id, private_pem, remote_ap_id) =
        seed_remote_signing_actor(&db, &remote_username, "remote.example").await;

    let follow_ap_id = format!("https://localhost/activities/{}", Uuid::new_v4());
    sqlx::query(
        "INSERT INTO followers (id, ap_id, follower_id, following_id, accepted, created_at) \
         VALUES ($1, $2, $3, $4, false, now())",
    )
    .bind(Uuid::new_v4())
    .bind(&follow_ap_id)
    .bind(local_id)
    .bind(remote_id)
    .execute(&db)
    .await
    .unwrap();

    let activity_id = format!("https://remote.example/activities/{}", Uuid::new_v4());
    let body = json!({
        "id": activity_id,
        "type": "Accept",
        "actor": remote_ap_id,
        "object": { "type": "Follow", "actor": local_ap_id, "object": remote_ap_id },
    });
    let key_id = format!("{remote_ap_id}#main-key");

    let req = build_signed_request("/inbox", &private_pem, &key_id, &body);
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::ACCEPTED);

    let accepted: bool = sqlx::query_scalar("SELECT accepted FROM followers WHERE ap_id = $1")
        .bind(&follow_ap_id)
        .fetch_one(&db)
        .await
        .unwrap();
    assert!(accepted);
}

#[tokio::test]
async fn inbox_reject_deletes_follow() {
    let (app, db) = test_app_with_db().await;
    let local_username = format!("local{}", Uuid::new_v4().simple());
    let local_id = seed_local_actor(&db, &local_username).await;
    let local_ap_id = format!("https://localhost/users/{local_username}");

    let remote_username = format!("remote{}", Uuid::new_v4().simple());
    let (remote_id, private_pem, remote_ap_id) =
        seed_remote_signing_actor(&db, &remote_username, "remote.example").await;

    let follow_ap_id = format!("https://localhost/activities/{}", Uuid::new_v4());
    sqlx::query(
        "INSERT INTO followers (id, ap_id, follower_id, following_id, accepted, created_at) \
         VALUES ($1, $2, $3, $4, false, now())",
    )
    .bind(Uuid::new_v4())
    .bind(&follow_ap_id)
    .bind(local_id)
    .bind(remote_id)
    .execute(&db)
    .await
    .unwrap();

    let activity_id = format!("https://remote.example/activities/{}", Uuid::new_v4());
    let body = json!({
        "id": activity_id,
        "type": "Reject",
        "actor": remote_ap_id,
        "object": { "type": "Follow", "actor": local_ap_id, "object": remote_ap_id },
    });
    let key_id = format!("{remote_ap_id}#main-key");

    let req = build_signed_request("/inbox", &private_pem, &key_id, &body);
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::ACCEPTED);

    let remaining: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM followers WHERE ap_id = $1")
        .bind(&follow_ap_id)
        .fetch_one(&db)
        .await
        .unwrap();
    assert_eq!(remaining, 0);
}

#[tokio::test]
async fn inbox_block_creates_block_and_removes_mutual_follows() {
    let (app, db) = test_app_with_db().await;
    let target_username = format!("target{}", Uuid::new_v4().simple());
    let target_id = seed_local_actor(&db, &target_username).await;
    let target_ap_id = format!("https://localhost/users/{target_username}");

    let remote_username = format!("remote{}", Uuid::new_v4().simple());
    let (blocker_id, private_pem, blocker_ap_id) =
        seed_remote_signing_actor(&db, &remote_username, "remote.example").await;

    seed_follow(&db, blocker_id, target_id).await;
    seed_follow(&db, target_id, blocker_id).await;

    let activity_id = format!("https://remote.example/activities/{}", Uuid::new_v4());
    let body = json!({
        "id": activity_id,
        "type": "Block",
        "actor": blocker_ap_id,
        "object": target_ap_id,
    });
    let key_id = format!("{blocker_ap_id}#main-key");

    let req = build_signed_request("/inbox", &private_pem, &key_id, &body);
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::ACCEPTED);

    let blocked: bool = sqlx::query_scalar(
        "SELECT EXISTS(SELECT 1 FROM user_blocks WHERE actor_id = $1 AND target_id = $2)",
    )
    .bind(blocker_id)
    .bind(target_id)
    .fetch_one(&db)
    .await
    .unwrap();
    assert!(blocked);

    let remaining_follows: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM followers WHERE \
            (follower_id = $1 AND following_id = $2) OR (follower_id = $2 AND following_id = $1)",
    )
    .bind(blocker_id)
    .bind(target_id)
    .fetch_one(&db)
    .await
    .unwrap();
    assert_eq!(remaining_follows, 0);
}

#[tokio::test]
async fn inbox_undo_follow_removes_existing_follow() {
    let (app, db) = test_app_with_db().await;
    let target_username = format!("target{}", Uuid::new_v4().simple());
    let target_id = seed_local_actor(&db, &target_username).await;
    let target_ap_id = format!("https://localhost/users/{target_username}");

    let remote_username = format!("remote{}", Uuid::new_v4().simple());
    let (follower_id, private_pem, follower_ap_id) =
        seed_remote_signing_actor(&db, &remote_username, "remote.example").await;

    seed_follow(&db, follower_id, target_id).await;

    let activity_id = format!("https://remote.example/activities/{}", Uuid::new_v4());
    let body = json!({
        "id": activity_id,
        "type": "Undo",
        "actor": follower_ap_id,
        "object": {
            "type": "Follow",
            "actor": follower_ap_id,
            "object": target_ap_id,
        },
    });
    let key_id = format!("{follower_ap_id}#main-key");

    let req = build_signed_request("/inbox", &private_pem, &key_id, &body);
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::ACCEPTED);

    let remaining: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM followers WHERE follower_id = $1 AND following_id = $2",
    )
    .bind(follower_id)
    .bind(target_id)
    .fetch_one(&db)
    .await
    .unwrap();
    assert_eq!(remaining, 0);
}

#[tokio::test]
async fn inbox_undo_follow_rejects_inner_actor_spoofing_another_sender() {
    let (app, db) = test_app_with_db().await;
    let target_username = format!("target{}", Uuid::new_v4().simple());
    let target_id = seed_local_actor(&db, &target_username).await;
    let target_ap_id = format!("https://localhost/users/{target_username}");

    let remote_username = format!("remote{}", Uuid::new_v4().simple());
    let (follower_id, private_pem, follower_ap_id) =
        seed_remote_signing_actor(&db, &remote_username, "remote.example").await;

    seed_follow(&db, follower_id, target_id).await;

    // 署名者(follower_ap_id)とは別の actor が inner.actor に書かれている
    // (他者のFollowを勝手に取り消そうとする spoofing 試行)。
    let activity_id = format!("https://remote.example/activities/{}", Uuid::new_v4());
    let body = json!({
        "id": activity_id,
        "type": "Undo",
        "actor": follower_ap_id,
        "object": {
            "type": "Follow",
            "actor": "https://attacker.example/users/mallory",
            "object": target_ap_id,
        },
    });
    let key_id = format!("{follower_ap_id}#main-key");

    let req = build_signed_request("/inbox", &private_pem, &key_id, &body);
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::ACCEPTED);

    // 署名者と inner.actor が一致しないため Undo は無視され、Follow は残る。
    let remaining: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM followers WHERE follower_id = $1 AND following_id = $2",
    )
    .bind(follower_id)
    .bind(target_id)
    .fetch_one(&db)
    .await
    .unwrap();
    assert_eq!(remaining, 1);
}

#[tokio::test]
async fn inbox_delete_note_soft_deletes_when_owned_by_actor() {
    let (app, db) = test_app_with_db().await;
    let remote_username = format!("remote{}", Uuid::new_v4().simple());
    let (actor_id, private_pem, actor_ap_id) =
        seed_remote_signing_actor(&db, &remote_username, "remote.example").await;

    let note_id = seed_note(&db, actor_id, chrono::Utc::now()).await;
    let note_ap_id = format!("https://localhost/notes/{note_id}");

    let activity_id = format!("https://remote.example/activities/{}", Uuid::new_v4());
    let body = json!({
        "id": activity_id,
        "type": "Delete",
        "actor": actor_ap_id,
        "object": { "id": note_ap_id, "type": "Tombstone" },
    });
    let key_id = format!("{actor_ap_id}#main-key");

    let req = build_signed_request("/inbox", &private_pem, &key_id, &body);
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::ACCEPTED);

    let deleted_at: Option<chrono::DateTime<chrono::Utc>> =
        sqlx::query_scalar("SELECT deleted_at FROM notes WHERE id = $1")
            .bind(note_id)
            .fetch_one(&db)
            .await
            .unwrap();
    assert!(deleted_at.is_some());
}

#[tokio::test]
async fn inbox_delete_note_denies_when_actor_does_not_own_note() {
    let (app, db) = test_app_with_db().await;
    let owner_username = format!("owner{}", Uuid::new_v4().simple());
    let owner_id = seed_local_actor(&db, &owner_username).await;
    let note_id = seed_note(&db, owner_id, chrono::Utc::now()).await;
    let note_ap_id = format!("https://localhost/notes/{note_id}");

    let remote_username = format!("remote{}", Uuid::new_v4().simple());
    let (_actor_id, private_pem, actor_ap_id) =
        seed_remote_signing_actor(&db, &remote_username, "remote.example").await;

    let activity_id = format!("https://remote.example/activities/{}", Uuid::new_v4());
    let body = json!({
        "id": activity_id,
        "type": "Delete",
        "actor": actor_ap_id,
        "object": { "id": note_ap_id, "type": "Tombstone" },
    });
    let key_id = format!("{actor_ap_id}#main-key");

    let req = build_signed_request("/inbox", &private_pem, &key_id, &body);
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::ACCEPTED);

    let deleted_at: Option<chrono::DateTime<chrono::Utc>> =
        sqlx::query_scalar("SELECT deleted_at FROM notes WHERE id = $1")
            .bind(note_id)
            .fetch_one(&db)
            .await
            .unwrap();
    assert!(deleted_at.is_none());
}

#[tokio::test]
async fn inbox_delete_person_soft_deletes_remote_actor_and_notes() {
    let (app, db) = test_app_with_db().await;
    let remote_username = format!("remote{}", Uuid::new_v4().simple());
    let (actor_id, private_pem, actor_ap_id) =
        seed_remote_signing_actor(&db, &remote_username, "remote.example").await;
    let note_id = seed_note(&db, actor_id, chrono::Utc::now()).await;

    let activity_id = format!("https://remote.example/activities/{}", Uuid::new_v4());
    let body = json!({
        "id": activity_id,
        "type": "Delete",
        "actor": actor_ap_id,
        "object": actor_ap_id,
    });
    let key_id = format!("{actor_ap_id}#main-key");

    let req = build_signed_request("/inbox", &private_pem, &key_id, &body);
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::ACCEPTED);

    let actor_deleted_at: Option<chrono::DateTime<chrono::Utc>> =
        sqlx::query_scalar("SELECT deleted_at FROM actors WHERE id = $1")
            .bind(actor_id)
            .fetch_one(&db)
            .await
            .unwrap();
    assert!(actor_deleted_at.is_some());

    let note_deleted_at: Option<chrono::DateTime<chrono::Utc>> =
        sqlx::query_scalar("SELECT deleted_at FROM notes WHERE id = $1")
            .bind(note_id)
            .fetch_one(&db)
            .await
            .unwrap();
    assert!(note_deleted_at.is_some());
}

#[tokio::test]
async fn inbox_flag_creates_report() {
    let (app, db) = test_app_with_db().await;
    let target_username = format!("target{}", Uuid::new_v4().simple());
    let target_id = seed_local_actor(&db, &target_username).await;
    let target_ap_id = format!("https://localhost/users/{target_username}");

    let remote_username = format!("remote{}", Uuid::new_v4().simple());
    let (reporter_id, private_pem, reporter_ap_id) =
        seed_remote_signing_actor(&db, &remote_username, "remote.example").await;

    let activity_id = format!("https://remote.example/activities/{}", Uuid::new_v4());
    let body = json!({
        "id": activity_id,
        "type": "Flag",
        "actor": reporter_ap_id,
        "object": [target_ap_id],
        "content": "spam",
    });
    let key_id = format!("{reporter_ap_id}#main-key");

    let req = build_signed_request("/inbox", &private_pem, &key_id, &body);
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::ACCEPTED);

    let (comment, target_actor_id): (Option<String>, Uuid) =
        sqlx::query_as("SELECT comment, target_actor_id FROM reports WHERE reporter_actor_id = $1")
            .bind(reporter_id)
            .fetch_one(&db)
            .await
            .unwrap();
    assert_eq!(comment.as_deref(), Some("spam"));
    assert_eq!(target_actor_id, target_id);
}

#[tokio::test]
async fn inbox_rejects_missing_signature() {
    let (app, _db) = test_app_with_db().await;
    let req = Request::builder()
        .method("POST")
        .uri("/inbox")
        .header("content-type", "application/activity+json")
        .header("x-real-ip", unique_ip())
        .header("digest", digest_header_for(b"{}"))
        .body(Body::from("{}"))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNAUTHORIZED);
}

#[tokio::test]
async fn inbox_rejects_tampered_digest() {
    let (app, db) = test_app_with_db().await;
    let remote_username = format!("remote{}", Uuid::new_v4().simple());
    let (_actor_id, private_pem, actor_ap_id) =
        seed_remote_signing_actor(&db, &remote_username, "remote.example").await;

    let activity_id = format!("https://remote.example/activities/{}", Uuid::new_v4());
    let body =
        json!({ "id": activity_id, "type": "Follow", "actor": actor_ap_id, "object": actor_ap_id });
    let key_id = format!("{actor_ap_id}#main-key");
    let mut req = build_signed_request("/inbox", &private_pem, &key_id, &body);

    // Digestヘッダーを実際のボディと不一致な値に差し替える。
    req.headers_mut().insert(
        "digest",
        "SHA-256=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
            .parse()
            .unwrap(),
    );

    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::BAD_REQUEST);
}

#[tokio::test]
async fn inbox_rejects_key_actor_mismatch() {
    let (app, db) = test_app_with_db().await;
    let remote_username = format!("remote{}", Uuid::new_v4().simple());
    let (_actor_id, private_pem, actor_ap_id) =
        seed_remote_signing_actor(&db, &remote_username, "remote.example").await;

    // activity.actor が署名鍵の持ち主と異なるなりすまし試行。
    let activity_id = format!("https://remote.example/activities/{}", Uuid::new_v4());
    let body = json!({
        "id": activity_id,
        "type": "Follow",
        "actor": "https://attacker.example/users/mallory",
        "object": actor_ap_id,
    });
    let key_id = format!("{actor_ap_id}#main-key");

    let req = build_signed_request("/inbox", &private_pem, &key_id, &body);
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNAUTHORIZED);
}

#[tokio::test]
async fn inbox_rejects_unknown_signing_key() {
    let (app, _db) = test_app_with_db().await;
    let mut rng = rand::thread_rng();
    let private_key = RsaPrivateKey::new(&mut rng, 2048).unwrap();
    let private_pem = private_key
        .to_pkcs8_pem(LineEnding::LF)
        .unwrap()
        .to_string();

    // DBに存在しない未知のactor(ネットワークフェッチも失敗する架空ドメイン)。
    let fake_ap_id = "http://127.0.0.1:1/users/nobody";
    let activity_id = "https://remote.example/activities/unknown";
    let body =
        json!({ "id": activity_id, "type": "Follow", "actor": fake_ap_id, "object": fake_ap_id });
    let key_id = format!("{fake_ap_id}#main-key");

    let req = build_signed_request("/inbox", &private_pem, &key_id, &body);
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::UNAUTHORIZED);
}

#[tokio::test]
async fn inbox_user_inbox_404_for_unknown_username() {
    let (app, _db) = test_app_with_db().await;
    let req = Request::builder()
        .method("POST")
        .uri(format!(
            "/users/nonexistent{}/inbox",
            Uuid::new_v4().simple()
        ))
        .header("x-real-ip", unique_ip())
        .body(Body::from("{}"))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::NOT_FOUND);
}

#[tokio::test]
async fn inbox_rejects_oversized_body() {
    let (app, db) = test_app_with_db().await;
    let remote_username = format!("remote{}", Uuid::new_v4().simple());
    let (_actor_id, _private_pem, actor_ap_id) =
        seed_remote_signing_actor(&db, &remote_username, "remote.example").await;

    let oversized = "x".repeat(2 * 1024 * 1024);
    let req = Request::builder()
        .method("POST")
        .uri("/inbox")
        .header("content-type", "application/activity+json")
        .header("x-real-ip", unique_ip())
        .header("content-length", oversized.len().to_string())
        .body(Body::from(oversized))
        .unwrap();
    let _ = actor_ap_id;
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::PAYLOAD_TOO_LARGE);
}

#[tokio::test]
async fn inbox_rate_limit_returns_429_after_threshold() {
    let (app, _db) = test_app_with_db().await;
    let ip = unique_ip();

    for _ in 0..200 {
        let req = Request::builder()
            .method("POST")
            .uri("/inbox")
            .header("x-real-ip", &ip)
            .header("digest", digest_header_for(b"{}"))
            .body(Body::from("{}"))
            .unwrap();
        let resp = app.clone().oneshot(req).await.unwrap();
        // 署名なしなので毎回401だが、レート制限はそれより前に評価される。
        assert_eq!(resp.status(), StatusCode::UNAUTHORIZED);
    }

    let req = Request::builder()
        .method("POST")
        .uri("/inbox")
        .header("x-real-ip", &ip)
        .header("digest", digest_header_for(b"{}"))
        .body(Body::from("{}"))
        .unwrap();
    let resp = app.oneshot(req).await.unwrap();
    assert_eq!(resp.status(), StatusCode::TOO_MANY_REQUESTS);
}
