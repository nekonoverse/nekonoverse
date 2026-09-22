use chrono::Utc;
use nekonoverse_backend_rs::remote_actor::{fetch_remote_actor, get_actor_public_key};
use nekonoverse_backend_rs::{config::Config, db, state::AppState, valkey};
use rsa::pkcs8::EncodePrivateKey;
use rsa::RsaPrivateKey;
use serde_json::json;
use sqlx::PgPool;
use uuid::Uuid;
use wiremock::matchers::{method, path};
use wiremock::{Mock, MockServer, ResponseTemplate};

mod common;
use common::seed_local_actor;

/// SSRF保護でwiremockの`127.0.0.1`宛リクエストがブロックされないよう
/// `allow_private_networks: true`にした`AppState`を組み立てる。
async fn test_state(db: PgPool) -> AppState {
    let mut config = Config::from_env();
    config.allow_private_networks = true;
    let redis = valkey::connect(&config)
        .await
        .expect("failed to connect to test valkey");
    AppState { db, redis, config }
}

async fn test_db() -> PgPool {
    db::connect(&Config::from_env())
        .await
        .expect("failed to connect to test database")
}

/// ローカル署名用アクター(実際にパース可能なRSA鍵ペア付き)を1件投入する。
/// `tests/common::seed_local_actor`/`seed_user`は'dummy-pem'を使うため、
/// `sign_request`が実際に成功する鍵が要るこのテストファイル専用に用意する。
async fn seed_signing_user(db: &PgPool, username: &str) -> Uuid {
    let mut rng = rand::thread_rng();
    let private_key = RsaPrivateKey::new(&mut rng, 2048).unwrap();
    let private_pem = private_key
        .to_pkcs8_pem(rsa::pkcs8::LineEnding::LF)
        .unwrap()
        .to_string();

    let actor_id = seed_local_actor(db, username).await;
    sqlx::query(
        r#"
        INSERT INTO users (
            id, email, password_hash, actor_id, role, is_active, is_system,
            private_key_pem, approval_status, created_at
        ) VALUES ($1, $2, 'dummy-hash', $3, 'user', true, false, $4, 'approved', now())
        "#,
    )
    .bind(Uuid::new_v4())
    .bind(format!("{username}@example.com"))
    .bind(actor_id)
    .bind(&private_pem)
    .execute(db)
    .await
    .unwrap();
    actor_id
}

fn remote_actor_json(server_uri: &str, username: &str) -> serde_json::Value {
    json!({
        "id": format!("{server_uri}/users/{username}"),
        "type": "Person",
        "preferredUsername": username,
        "name": "Remote Test User",
        "summary": "<p>hello</p>",
        "inbox": format!("{server_uri}/users/{username}/inbox"),
        "outbox": format!("{server_uri}/users/{username}/outbox"),
        "followers": format!("{server_uri}/users/{username}/followers"),
        "following": format!("{server_uri}/users/{username}/following"),
        "publicKey": {
            "id": format!("{server_uri}/users/{username}#main-key"),
            "publicKeyPem": "-----BEGIN PUBLIC KEY-----\nMFAKE\n-----END PUBLIC KEY-----",
        },
        "icon": { "url": format!("{server_uri}/avatar.png") },
        "manuallyApprovesFollowers": true,
        "discoverable": true,
    })
}

#[tokio::test]
async fn fetch_remote_actor_creates_new_row_from_signed_fetch() {
    let db = test_db().await;
    let _signer = seed_signing_user(&db, &format!("signer{}", Uuid::new_v4().simple())).await;
    let state = test_state(db).await;

    let mock_server = MockServer::start().await;
    let username = format!("alice{}", Uuid::new_v4().simple());
    let body = remote_actor_json(&mock_server.uri(), &username);
    let ap_id = body["id"].as_str().unwrap().to_string();

    Mock::given(method("GET"))
        .and(path(format!("/users/{username}")))
        .respond_with(
            ResponseTemplate::new(200)
                .set_body_json(body.clone())
                .insert_header("content-type", "application/activity+json"),
        )
        .expect(1)
        .mount(&mock_server)
        .await;

    let actor = fetch_remote_actor(&state, &ap_id)
        .await
        .unwrap()
        .expect("actor should be fetched and upserted");

    assert_eq!(actor.ap_id, ap_id);
    assert_eq!(actor.username, username);
    assert_eq!(actor.display_name.as_deref(), Some("Remote Test User"));
    assert_eq!(actor.summary.as_deref(), Some("<p>hello</p>"));
    assert!(actor.manually_approves_followers);
    assert!(actor.discoverable);
    assert_eq!(
        actor.avatar_url.as_deref(),
        Some(format!("{}/avatar.png", mock_server.uri()).as_str())
    );

    // 実際にDBへ反映されていることも確認する。
    let stored_username: String =
        sqlx::query_scalar("SELECT username FROM actors WHERE ap_id = $1")
            .bind(&ap_id)
            .fetch_one(&state.db)
            .await
            .unwrap();
    assert_eq!(stored_username, username);

    // wiremockの`.expect(1)`がリクエストのSignatureヘッダー有無まではmatcherで
    // 見ていないため、ここで別途「署名ヘッダーが付与されていたか」を検証する。
    let requests = mock_server.received_requests().await.unwrap();
    assert_eq!(requests.len(), 1);
    assert!(requests[0].headers.contains_key("signature"));
    assert!(requests[0].headers.contains_key("date"));
}

#[tokio::test]
async fn fetch_remote_actor_uses_cache_within_ttl() {
    let db = test_db().await;
    let _signer = seed_signing_user(&db, &format!("signer{}", Uuid::new_v4().simple())).await;
    let state = test_state(db).await;

    let mock_server = MockServer::start().await;
    let username = format!("cached{}", Uuid::new_v4().simple());
    let body = remote_actor_json(&mock_server.uri(), &username);
    let ap_id = body["id"].as_str().unwrap().to_string();

    Mock::given(method("GET"))
        .and(path(format!("/users/{username}")))
        .respond_with(ResponseTemplate::new(200).set_body_json(body.clone()))
        .expect(1)
        .mount(&mock_server)
        .await;

    let first = fetch_remote_actor(&state, &ap_id).await.unwrap().unwrap();
    assert!(first.last_fetched_at.is_some());

    // 2回目はキャッシュ命中のはずなので、mockへのHTTPリクエストは増えない
    // (`.expect(1)`が守られる = mock_serverドロップ時に検証される)。
    let second = fetch_remote_actor(&state, &ap_id).await.unwrap().unwrap();
    assert_eq!(second.id, first.id);
}

#[tokio::test]
async fn fetch_remote_actor_rejects_domain_mismatch() {
    let db = test_db().await;
    let _signer = seed_signing_user(&db, &format!("signer{}", Uuid::new_v4().simple())).await;
    let state = test_state(db).await;

    let mock_server = MockServer::start().await;
    let username = format!("evil{}", Uuid::new_v4().simple());
    // レスポンスの`id`をリクエスト先と異なるドメインにする (スプーフィング試行)。
    let mut body = remote_actor_json(&mock_server.uri(), &username);
    body["id"] = json!("https://attacker.example/users/mallory");
    let ap_id = format!("{}/users/{username}", mock_server.uri());

    Mock::given(method("GET"))
        .and(path(format!("/users/{username}")))
        .respond_with(ResponseTemplate::new(200).set_body_json(body))
        .mount(&mock_server)
        .await;

    let actor = fetch_remote_actor(&state, &ap_id).await.unwrap();
    assert!(actor.is_none());

    let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM actors WHERE ap_id = $1")
        .bind(&ap_id)
        .fetch_one(&state.db)
        .await
        .unwrap();
    assert_eq!(count, 0);
}

#[tokio::test]
async fn fetch_remote_actor_returns_none_for_non_200() {
    let db = test_db().await;
    let _signer = seed_signing_user(&db, &format!("signer{}", Uuid::new_v4().simple())).await;
    let state = test_state(db).await;

    let mock_server = MockServer::start().await;
    let username = format!("missing{}", Uuid::new_v4().simple());
    let ap_id = format!("{}/users/{username}", mock_server.uri());

    Mock::given(method("GET"))
        .and(path(format!("/users/{username}")))
        .respond_with(ResponseTemplate::new(404))
        .mount(&mock_server)
        .await;

    let actor = fetch_remote_actor(&state, &ap_id).await.unwrap();
    assert!(actor.is_none());
}

#[tokio::test]
async fn fetch_remote_actor_blocks_private_network_target_by_default() {
    let db = test_db().await;
    // `allow_private_networks: false`のまま(本番デフォルト)。
    let config = Config::from_env();
    assert!(!config.allow_private_networks);
    let redis = valkey::connect(&config).await.unwrap();
    let state = AppState { db, redis, config };

    let actor = fetch_remote_actor(&state, "http://127.0.0.1:1/users/nobody")
        .await
        .unwrap();
    assert!(actor.is_none());
}

#[tokio::test]
async fn upsert_remote_actor_update_preserves_fields_absent_from_new_payload() {
    let db = test_db().await;
    let _signer = seed_signing_user(&db, &format!("signer{}", Uuid::new_v4().simple())).await;
    let state = test_state(db).await;

    let mock_server = MockServer::start().await;
    let username = format!("update{}", Uuid::new_v4().simple());
    let ap_id = format!("{}/users/{username}", mock_server.uri());

    let full_body = remote_actor_json(&mock_server.uri(), &username);
    Mock::given(method("GET"))
        .and(path(format!("/users/{username}")))
        .respond_with(ResponseTemplate::new(200).set_body_json(full_body.clone()))
        .up_to_n_times(1)
        .mount(&mock_server)
        .await;

    let first = fetch_remote_actor(&state, &ap_id).await.unwrap().unwrap();
    assert_eq!(
        first.outbox_url.as_deref(),
        Some(format!("{}/users/{username}/outbox", mock_server.uri()).as_str())
    );

    // last_fetched_atを1時間以上前にずらしてキャッシュを無効化し、
    // "outbox"キーを含まない(=省略された)レスポンスで再取得させる。
    sqlx::query("UPDATE actors SET last_fetched_at = $1 WHERE id = $2")
        .bind(Utc::now() - chrono::Duration::hours(2))
        .bind(first.id)
        .execute(&state.db)
        .await
        .unwrap();

    let mut partial_body = full_body.clone();
    partial_body.as_object_mut().unwrap().remove("outbox");
    Mock::given(method("GET"))
        .and(path(format!("/users/{username}")))
        .respond_with(ResponseTemplate::new(200).set_body_json(partial_body))
        .mount(&mock_server)
        .await;

    let second = fetch_remote_actor(&state, &ap_id).await.unwrap().unwrap();
    // outboxキー自体が無かったので既存値が保持されるはず
    // (`data.get("outbox", existing.outbox_url)`と同じ規則)。
    assert_eq!(second.outbox_url, first.outbox_url);
}

#[tokio::test]
async fn get_actor_public_key_returns_rsa_material_for_unknown_actor() {
    let db = test_db().await;
    let _signer = seed_signing_user(&db, &format!("signer{}", Uuid::new_v4().simple())).await;
    let state = test_state(db).await;

    let mock_server = MockServer::start().await;
    let username = format!("keyed{}", Uuid::new_v4().simple());
    let body = remote_actor_json(&mock_server.uri(), &username);
    let ap_id = body["id"].as_str().unwrap().to_string();
    let key_id = format!("{ap_id}#main-key");

    Mock::given(method("GET"))
        .and(path(format!("/users/{username}")))
        .respond_with(ResponseTemplate::new(200).set_body_json(body))
        .mount(&mock_server)
        .await;

    let info = get_actor_public_key(&state, &key_id)
        .await
        .unwrap()
        .expect("should resolve actor key");
    assert_eq!(info.algorithm, "rsa-sha256");
    assert!(info.public_key_material.contains("BEGIN PUBLIC KEY"));
}

#[tokio::test]
async fn upsert_remote_actor_ingests_custom_emoji_tags() {
    let db = test_db().await;
    let _signer = seed_signing_user(&db, &format!("signer{}", Uuid::new_v4().simple())).await;
    let state = test_state(db).await;

    let mock_server = MockServer::start().await;
    let username = format!("emoji{}", Uuid::new_v4().simple());
    let shortcode = format!("blob{}", Uuid::new_v4().simple());
    let mut body = remote_actor_json(&mock_server.uri(), &username);
    body["tag"] = json!([{
        "type": "Emoji",
        "name": format!(":{shortcode}:"),
        "icon": { "type": "Image", "url": format!("{}/emoji.png", mock_server.uri()) },
    }]);
    let ap_id = body["id"].as_str().unwrap().to_string();

    Mock::given(method("GET"))
        .and(path(format!("/users/{username}")))
        .respond_with(ResponseTemplate::new(200).set_body_json(body))
        .mount(&mock_server)
        .await;

    fetch_remote_actor(&state, &ap_id).await.unwrap();

    let domain = reqwest::Url::parse(&mock_server.uri())
        .unwrap()
        .host_str()
        .unwrap()
        .to_string();
    let stored_url: String =
        sqlx::query_scalar("SELECT url FROM custom_emojis WHERE shortcode = $1 AND domain = $2")
            .bind(&shortcode)
            .bind(&domain)
            .fetch_one(&state.db)
            .await
            .unwrap();
    assert_eq!(stored_url, format!("{}/emoji.png", mock_server.uri()));
}
