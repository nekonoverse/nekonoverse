use axum::body::Body;
use axum::http::{header, Request, StatusCode};
use serde_json::Value;
use tower::ServiceExt;
use uuid::Uuid;

mod common;
use chrono::Utc;
use common::{
    seed_drive_file, seed_follow, seed_local_actor, seed_note, seed_note_attachment,
    seed_note_with_visibility, seed_pinned_note, seed_remote_actor, seed_remote_note_attachment,
};

const AP_ACCEPT: &str = "application/activity+json";

async fn get(
    app: axum::Router,
    uri: &str,
    accept: Option<&str>,
) -> (StatusCode, axum::http::HeaderMap, Value, String) {
    let mut builder = Request::builder().method("GET").uri(uri);
    if let Some(accept) = accept {
        builder = builder.header(header::ACCEPT, accept);
    }
    let response = app
        .oneshot(builder.body(Body::empty()).unwrap())
        .await
        .unwrap();
    let status = response.status();
    let headers = response.headers().clone();
    let body = http_body_util::BodyExt::collect(response.into_body())
        .await
        .unwrap()
        .to_bytes();
    let raw = String::from_utf8_lossy(&body).to_string();
    let json: Value = if body.is_empty() {
        Value::Null
    } else {
        serde_json::from_slice(&body).unwrap_or(Value::Null)
    };
    (status, headers, json, raw)
}

#[tokio::test]
async fn get_actor_local_public_actor_returns_ap_json() {
    let (app, db) = common::test_app_with_db().await;
    let username = format!("actortest1{}", Uuid::new_v4().simple());
    seed_local_actor(&db, &username).await;

    let (status, headers, json, _raw) =
        get(app, &format!("/users/{username}"), Some(AP_ACCEPT)).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(
        headers.get(header::CONTENT_TYPE).unwrap(),
        "application/activity+json; charset=utf-8"
    );
    assert_eq!(json["type"], "Person");
    assert_eq!(json["preferredUsername"], username);
    assert_eq!(json["id"], format!("https://localhost/users/{username}"));
    assert_eq!(
        json["inbox"],
        format!("https://localhost/users/{username}/inbox")
    );
    assert_eq!(
        json["followers"],
        format!("https://localhost/users/{username}/followers")
    );
    assert_eq!(
        json["featured"],
        format!("https://localhost/users/{username}/featured")
    );
    assert_eq!(json["publicKey"]["publicKeyPem"], "dummy-pem");
    assert!(json.get("assertionMethod").is_none());
    assert!(json.get("summary").is_none());
    assert!(json.get("attachment").is_none());
}

#[tokio::test]
async fn get_actor_without_ap_accept_redirects_to_profile() {
    let (app, db) = common::test_app_with_db().await;
    let username = format!("actortest2{}", Uuid::new_v4().simple());
    seed_local_actor(&db, &username).await;

    let (status, headers, _json, _raw) = get(app, &format!("/users/{username}"), None).await;
    assert_eq!(status, StatusCode::FOUND);
    assert_eq!(
        headers.get(header::LOCATION).unwrap(),
        &format!("/@{username}")
    );
}

#[tokio::test]
async fn get_actor_not_found_returns_404() {
    let (app, _db) = common::test_app_with_db().await;
    let (status, _headers, json, _raw) = get(
        app,
        &format!("/users/nonexistent-{}", Uuid::new_v4().simple()),
        Some(AP_ACCEPT),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    assert_eq!(json["detail"], "Actor not found");
}

#[tokio::test]
async fn get_actor_deleted_returns_tombstone_for_ap_request() {
    let (app, db) = common::test_app_with_db().await;
    let username = format!("actortest4{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(&db, &username).await;
    sqlx::query("UPDATE actors SET deleted_at = now() WHERE id = $1")
        .bind(actor_id)
        .execute(&db)
        .await
        .unwrap();

    let (status, headers, json, _raw) =
        get(app, &format!("/users/{username}"), Some(AP_ACCEPT)).await;
    assert_eq!(status, StatusCode::GONE);
    assert_eq!(
        headers.get(header::CONTENT_TYPE).unwrap(),
        "application/activity+json; charset=utf-8"
    );
    assert_eq!(json["type"], "Tombstone");
    assert_eq!(json["@context"], "https://www.w3.org/ns/activitystreams");
}

#[tokio::test]
async fn get_actor_deleted_returns_plain_410_for_html_request() {
    let (app, db) = common::test_app_with_db().await;
    let username = format!("actortest5{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(&db, &username).await;
    sqlx::query("UPDATE actors SET deleted_at = now() WHERE id = $1")
        .bind(actor_id)
        .execute(&db)
        .await
        .unwrap();

    let (status, _headers, json, _raw) = get(app, &format!("/users/{username}"), None).await;
    assert_eq!(status, StatusCode::GONE);
    assert_eq!(json["detail"], "Gone");
}

#[tokio::test]
async fn get_actor_suspended_returns_410() {
    let (app, db) = common::test_app_with_db().await;
    let username = format!("actortest6{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(&db, &username).await;
    sqlx::query("UPDATE actors SET suspended_at = now() WHERE id = $1")
        .bind(actor_id)
        .execute(&db)
        .await
        .unwrap();

    let (status, _headers, json, _raw) =
        get(app, &format!("/users/{username}"), Some(AP_ACCEPT)).await;
    assert_eq!(status, StatusCode::GONE);
    assert_eq!(json["detail"], "Gone");
}

#[tokio::test]
async fn get_actor_includes_ed25519_assertion_method_when_present() {
    let (app, db) = common::test_app_with_db().await;
    let username = format!("actortest7{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(&db, &username).await;
    sqlx::query("UPDATE actors SET public_key_ed25519_multibase = $1 WHERE id = $2")
        .bind("z6MkTestMultibaseKey")
        .bind(actor_id)
        .execute(&db)
        .await
        .unwrap();

    let (status, _headers, json, _raw) =
        get(app, &format!("/users/{username}"), Some(AP_ACCEPT)).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(
        json["assertionMethod"][0]["publicKeyMultibase"],
        "z6MkTestMultibaseKey"
    );
    assert_eq!(json["assertionMethod"][0]["type"], "Multikey");
}

#[tokio::test]
async fn get_actor_includes_fields_as_attachment() {
    let (app, db) = common::test_app_with_db().await;
    let username = format!("actortest8{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(&db, &username).await;
    sqlx::query("UPDATE actors SET fields = $1::jsonb WHERE id = $2")
        .bind(r#"[{"name": "Website", "value": "https://example.com"}]"#)
        .bind(actor_id)
        .execute(&db)
        .await
        .unwrap();

    let (status, _headers, json, _raw) =
        get(app, &format!("/users/{username}"), Some(AP_ACCEPT)).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(json["attachment"][0]["type"], "PropertyValue");
    assert_eq!(json["attachment"][0]["name"], "Website");
    assert_eq!(json["attachment"][0]["value"], "https://example.com");
}

#[tokio::test]
async fn get_followers_collection_without_page_returns_count_only() {
    let (app, db) = common::test_app_with_db().await;
    let username = format!("followerstest1{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(&db, &username).await;
    let domain = format!("remote-ft1-{}.example", Uuid::new_v4().simple());
    let remote_id = seed_remote_actor(&db, "remote-ft1", &domain).await;
    seed_follow(&db, remote_id, actor_id).await;

    let (status, headers, json, _raw) =
        get(app, &format!("/users/{username}/followers"), None).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(
        headers.get(header::CONTENT_TYPE).unwrap(),
        "application/activity+json; charset=utf-8"
    );
    assert_eq!(json["type"], "OrderedCollection");
    assert_eq!(json["totalItems"], 1);
    assert_eq!(
        json["first"],
        format!("https://localhost/users/{username}/followers?page=true")
    );
    assert!(json.get("orderedItems").is_none());
}

#[tokio::test]
async fn get_followers_collection_page_returns_follower_ap_ids() {
    let (app, db) = common::test_app_with_db().await;
    let username = format!("followerstest2{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(&db, &username).await;
    let domain = format!("remote-ft2-{}.example", Uuid::new_v4().simple());
    let remote_id = seed_remote_actor(&db, "remote-ft2", &domain).await;
    seed_follow(&db, remote_id, actor_id).await;

    let (status, _headers, json, _raw) =
        get(app, &format!("/users/{username}/followers?page=true"), None).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(json["type"], "OrderedCollectionPage");
    assert_eq!(
        json["orderedItems"][0],
        format!("https://{domain}/users/remote-ft2")
    );
    assert!(json.get("next").is_none());
}

#[tokio::test]
async fn get_followers_collection_excludes_unaccepted_follow() {
    let (app, db) = common::test_app_with_db().await;
    let username = format!("followerstest3{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(&db, &username).await;
    let domain = format!("remote-ft3-{}.example", Uuid::new_v4().simple());
    let remote_id = seed_remote_actor(&db, "remote-ft3", &domain).await;
    sqlx::query(
        "INSERT INTO followers (id, follower_id, following_id, accepted, created_at) \
         VALUES ($1, $2, $3, false, now())",
    )
    .bind(Uuid::new_v4())
    .bind(remote_id)
    .bind(actor_id)
    .execute(&db)
    .await
    .unwrap();

    let (status, _headers, json, _raw) =
        get(app, &format!("/users/{username}/followers?page=true"), None).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(json["orderedItems"].as_array().unwrap().len(), 0);
}

#[tokio::test]
async fn get_followers_collection_not_found_actor_returns_404() {
    let (app, _db) = common::test_app_with_db().await;
    let (status, _headers, json, _raw) = get(
        app,
        &format!("/users/nonexistent-{}/followers", Uuid::new_v4().simple()),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    assert_eq!(json["detail"], "Actor not found");
}

#[tokio::test]
async fn get_following_collection_page_returns_following_ap_ids() {
    let (app, db) = common::test_app_with_db().await;
    let username = format!("followingtest1{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(&db, &username).await;
    let domain = format!("remote-gt1-{}.example", Uuid::new_v4().simple());
    let remote_id = seed_remote_actor(&db, "remote-gt1", &domain).await;
    seed_follow(&db, actor_id, remote_id).await;

    let (status, _headers, json, _raw) =
        get(app, &format!("/users/{username}/following?page=true"), None).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(json["type"], "OrderedCollectionPage");
    assert_eq!(
        json["orderedItems"][0],
        format!("https://{domain}/users/remote-gt1")
    );
}

#[tokio::test]
async fn get_following_collection_without_page_returns_count_only() {
    let (app, db) = common::test_app_with_db().await;
    let username = format!("followingtest2{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(&db, &username).await;
    let domain = format!("remote-gt2-{}.example", Uuid::new_v4().simple());
    let remote_id = seed_remote_actor(&db, "remote-gt2", &domain).await;
    seed_follow(&db, actor_id, remote_id).await;

    let (status, _headers, json, _raw) =
        get(app, &format!("/users/{username}/following"), None).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(json["type"], "OrderedCollection");
    assert_eq!(json["totalItems"], 1);
}

#[tokio::test]
async fn get_outbox_without_page_returns_count_only() {
    let (app, db) = common::test_app_with_db().await;
    let username = format!("outboxtest1{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(&db, &username).await;
    seed_note(&db, actor_id, Utc::now()).await;

    let (status, headers, json, _raw) = get(app, &format!("/users/{username}/outbox"), None).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(
        headers.get(header::CONTENT_TYPE).unwrap(),
        "application/activity+json; charset=utf-8"
    );
    assert_eq!(json["type"], "OrderedCollection");
    assert_eq!(json["totalItems"], 1);
    assert_eq!(
        json["first"],
        format!("https://localhost/users/{username}/outbox?page=true")
    );
    assert!(json.get("orderedItems").is_none());
}

#[tokio::test]
async fn get_outbox_not_found_actor_returns_404() {
    let (app, _db) = common::test_app_with_db().await;
    let (status, _headers, json, _raw) = get(
        app,
        &format!("/users/nonexistent-{}/outbox", Uuid::new_v4().simple()),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    assert_eq!(json["detail"], "Actor not found");
}

#[tokio::test]
async fn get_outbox_page_renders_create_activity_wrapping_note() {
    let (app, db) = common::test_app_with_db().await;
    let username = format!("outboxtest2{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(&db, &username).await;
    let note_id = seed_note(&db, actor_id, Utc::now()).await;

    let (status, _headers, json, _raw) =
        get(app, &format!("/users/{username}/outbox?page=true"), None).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(json["type"], "OrderedCollectionPage");
    let activity = &json["orderedItems"][0];
    assert_eq!(activity["type"], "Create");
    assert_eq!(
        activity["id"],
        format!("https://localhost/notes/{note_id}/activity")
    );
    assert_eq!(
        activity["actor"],
        format!("https://localhost/users/{username}")
    );
    assert_eq!(activity["object"]["type"], "Note");
    assert_eq!(activity["object"]["content"], "test note");
    assert_eq!(
        activity["object"]["attributedTo"],
        format!("https://localhost/users/{username}")
    );
    assert_eq!(
        activity["object"]["url"],
        format!("https://localhost/notes/{note_id}")
    );
}

#[tokio::test]
async fn get_outbox_excludes_non_public_and_remote_and_deleted_notes() {
    let (app, db) = common::test_app_with_db().await;
    let username = format!("outboxtest3{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(&db, &username).await;
    seed_note_with_visibility(&db, actor_id, "unlisted", Utc::now()).await;
    seed_note_with_visibility(&db, actor_id, "followers", Utc::now()).await;
    let deleted_id = seed_note(&db, actor_id, Utc::now()).await;
    sqlx::query("UPDATE notes SET deleted_at = now() WHERE id = $1")
        .bind(deleted_id)
        .execute(&db)
        .await
        .unwrap();

    let (status, _headers, json, _raw) =
        get(app, &format!("/users/{username}/outbox?page=true"), None).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(json["orderedItems"].as_array().unwrap().len(), 0);
}

#[tokio::test]
async fn get_outbox_note_with_drive_file_attachment_renders_document() {
    let (app, db) = common::test_app_with_db().await;
    let username = format!("outboxtest4{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(&db, &username).await;
    let note_id = seed_note(&db, actor_id, Utc::now()).await;
    let s3_key = format!("outbox-test/{}-cat.png", Uuid::new_v4().simple());
    let drive_file_id = seed_drive_file(&db, &s3_key, "image/png").await;
    sqlx::query(
        "UPDATE drive_files SET width = 100, height = 200, blurhash = 'LKO2?U%2Tw=w', \
         description = 'a cat' WHERE id = $1",
    )
    .bind(drive_file_id)
    .execute(&db)
    .await
    .unwrap();
    seed_note_attachment(&db, note_id, drive_file_id, 0).await;

    let (status, _headers, json, _raw) =
        get(app, &format!("/users/{username}/outbox?page=true"), None).await;
    assert_eq!(status, StatusCode::OK);
    let doc = &json["orderedItems"][0]["object"]["attachment"][0];
    assert_eq!(doc["type"], "Document");
    assert_eq!(doc["mediaType"], "image/png");
    assert_eq!(doc["url"], format!("https://localhost/media/{s3_key}"));
    assert_eq!(doc["name"], "a cat");
    assert_eq!(doc["width"], 100);
    assert_eq!(doc["height"], 200);
    assert_eq!(doc["blurhash"], "LKO2?U%2Tw=w");
}

#[tokio::test]
async fn get_outbox_note_with_remote_attachment_renders_document() {
    let (app, db) = common::test_app_with_db().await;
    let username = format!("outboxtest5{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(&db, &username).await;
    let note_id = seed_note(&db, actor_id, Utc::now()).await;
    seed_remote_note_attachment(
        &db,
        note_id,
        "https://remote.example/media/dog.jpg",
        "image/jpeg",
        0,
    )
    .await;

    let (status, _headers, json, _raw) =
        get(app, &format!("/users/{username}/outbox?page=true"), None).await;
    assert_eq!(status, StatusCode::OK);
    let doc = &json["orderedItems"][0]["object"]["attachment"][0];
    assert_eq!(doc["type"], "Document");
    assert_eq!(doc["mediaType"], "image/jpeg");
    assert_eq!(doc["url"], "https://remote.example/media/dog.jpg");
    assert!(doc.get("icon").is_none());
}

#[tokio::test]
async fn get_outbox_note_with_mention_renders_mention_tag() {
    let (app, db) = common::test_app_with_db().await;
    let username = format!("outboxtest6{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(&db, &username).await;
    let note_id = seed_note(&db, actor_id, Utc::now()).await;
    sqlx::query(
        r#"UPDATE notes SET mentions = '[{"ap_id": "https://remote.example/users/bob", "username": "bob", "domain": "remote.example"}]'::json WHERE id = $1"#,
    )
    .bind(note_id)
    .execute(&db)
    .await
    .unwrap();

    let (status, _headers, json, _raw) =
        get(app, &format!("/users/{username}/outbox?page=true"), None).await;
    assert_eq!(status, StatusCode::OK);
    let tag = &json["orderedItems"][0]["object"]["tag"][0];
    assert_eq!(tag["type"], "Mention");
    assert_eq!(tag["href"], "https://remote.example/users/bob");
    assert_eq!(tag["name"], "@bob@remote.example");
}

#[tokio::test]
async fn get_outbox_poll_note_renders_one_of_and_voters_count() {
    let (app, db) = common::test_app_with_db().await;
    let username = format!("outboxtest7{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(&db, &username).await;
    let note_id = seed_note(&db, actor_id, Utc::now()).await;
    sqlx::query(
        r#"UPDATE notes SET is_poll = true, poll_options = '[{"title": "cat", "votes_count": 3}, {"title": "dog", "votes_count": 2}]'::jsonb WHERE id = $1"#,
    )
    .bind(note_id)
    .execute(&db)
    .await
    .unwrap();

    let (status, _headers, json, _raw) =
        get(app, &format!("/users/{username}/outbox?page=true"), None).await;
    assert_eq!(status, StatusCode::OK);
    let object = &json["orderedItems"][0]["object"];
    assert_eq!(object["type"], "Question");
    assert_eq!(object["oneOf"][0]["name"], "cat");
    assert_eq!(object["votersCount"], 5);
}

#[tokio::test]
async fn get_featured_not_found_actor_returns_404() {
    let (app, _db) = common::test_app_with_db().await;
    let (status, _headers, json, _raw) = get(
        app,
        &format!("/users/nonexistent-{}/featured", Uuid::new_v4().simple()),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    assert_eq!(json["detail"], "Actor not found");
}

#[tokio::test]
async fn get_featured_renders_pinned_notes_in_position_order_without_create_wrapper() {
    let (app, db) = common::test_app_with_db().await;
    let username = format!("featuredtest1{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(&db, &username).await;
    let note_a = seed_note(&db, actor_id, Utc::now()).await;
    let note_b = seed_note(&db, actor_id, Utc::now()).await;
    // 逆順にピン留めして position の並び順を検証する。
    seed_pinned_note(&db, actor_id, note_b, 0).await;
    seed_pinned_note(&db, actor_id, note_a, 1).await;

    let (status, headers, json, _raw) =
        get(app, &format!("/users/{username}/featured"), None).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(
        headers.get(header::CONTENT_TYPE).unwrap(),
        "application/activity+json; charset=utf-8"
    );
    assert_eq!(json["type"], "OrderedCollection");
    assert_eq!(json["totalItems"], 2);
    assert_eq!(json["orderedItems"][0]["type"], "Note");
    assert_eq!(
        json["orderedItems"][0]["id"],
        format!("https://localhost/notes/{note_b}")
    );
    assert_eq!(
        json["orderedItems"][1]["id"],
        format!("https://localhost/notes/{note_a}")
    );
}

#[tokio::test]
async fn get_featured_excludes_followers_only_and_direct_pinned_notes() {
    let (app, db) = common::test_app_with_db().await;
    let username = format!("featuredtest2{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(&db, &username).await;
    let public_note = seed_note_with_visibility(&db, actor_id, "public", Utc::now()).await;
    let followers_note = seed_note_with_visibility(&db, actor_id, "followers", Utc::now()).await;
    let direct_note = seed_note_with_visibility(&db, actor_id, "direct", Utc::now()).await;
    seed_pinned_note(&db, actor_id, public_note, 0).await;
    seed_pinned_note(&db, actor_id, followers_note, 1).await;
    seed_pinned_note(&db, actor_id, direct_note, 2).await;

    let (status, _headers, json, _raw) =
        get(app, &format!("/users/{username}/featured"), None).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(json["totalItems"], 1);
    assert_eq!(
        json["orderedItems"][0]["id"],
        format!("https://localhost/notes/{public_note}")
    );
}

#[tokio::test]
async fn get_featured_excludes_notes_hidden_by_make_notes_hidden_before() {
    let (app, db) = common::test_app_with_db().await;
    let username = format!("featuredtest3{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(&db, &username).await;
    let old_published = chrono::DateTime::parse_from_rfc3339("2020-01-01T00:00:00Z")
        .unwrap()
        .with_timezone(&Utc);
    let old_note = seed_note_with_visibility(&db, actor_id, "public", old_published).await;
    seed_pinned_note(&db, actor_id, old_note, 0).await;
    sqlx::query("UPDATE actors SET make_notes_hidden_before = $1 WHERE id = $2")
        .bind(Utc::now().timestamp_millis())
        .bind(actor_id)
        .execute(&db)
        .await
        .unwrap();

    let (status, _headers, json, _raw) =
        get(app, &format!("/users/{username}/featured"), None).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(json["totalItems"], 0);
}
