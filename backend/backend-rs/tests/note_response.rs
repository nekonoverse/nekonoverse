use chrono::{Duration, Utc};
use nekonoverse_backend_rs::config::Config;
use nekonoverse_backend_rs::note_response::{
    fetch_note_render_row, get_poll_data_json, get_reaction_summary, note_to_response_json,
};
use serde_json::json;
use uuid::Uuid;

mod common;
use common::{
    connect_redis, seed_custom_emoji, seed_drive_file, seed_hashtag_for_note, seed_local_actor,
    seed_note, seed_note_attachment, seed_note_with_visibility, seed_poll_vote, seed_preview_card,
    seed_reaction, seed_remote_actor, seed_remote_note_attachment,
};

fn config() -> Config {
    Config::from_env()
}

#[tokio::test]
async fn fetch_note_render_row_returns_note_and_actor_fields() {
    let (_app, db) = common::test_app_with_db().await;
    let username = format!("noteresp1{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(&db, &username).await;
    let note_id = seed_note_with_visibility(&db, actor_id, "public", Utc::now()).await;

    let row = fetch_note_render_row(&db, note_id)
        .await
        .unwrap()
        .expect("note should exist");
    assert_eq!(row.id, note_id);
    assert_eq!(row.actor_username, username);
    assert_eq!(row.visibility, "public");
}

#[tokio::test]
async fn fetch_note_render_row_returns_none_for_deleted_note() {
    let (_app, db) = common::test_app_with_db().await;
    let actor_id = seed_local_actor(&db, &format!("noteresp2{}", Uuid::new_v4().simple())).await;
    let note_id = seed_note_with_visibility(&db, actor_id, "public", Utc::now()).await;
    sqlx::query("UPDATE notes SET deleted_at = now() WHERE id = $1")
        .bind(note_id)
        .execute(&db)
        .await
        .unwrap();

    assert!(fetch_note_render_row(&db, note_id).await.unwrap().is_none());
}

#[tokio::test]
async fn note_to_response_json_basic_shape() {
    let (_app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let config = config();
    let username = format!("noteresp3{}", Uuid::new_v4().simple());
    let actor_id = seed_local_actor(&db, &username).await;
    let note_id = seed_note_with_visibility(&db, actor_id, "followers", Utc::now()).await;

    let row = fetch_note_render_row(&db, note_id).await.unwrap().unwrap();
    let resp = note_to_response_json(
        &db,
        &config,
        &redis,
        &row,
        &[],
        None,
        None,
        None,
        false,
        false,
    )
    .await
    .unwrap();

    assert_eq!(resp["id"], note_id.to_string());
    assert_eq!(resp["ap_id"], row.ap_id);
    assert_eq!(resp["uri"], row.ap_id);
    assert_eq!(resp["content"], "test note");
    // "followers" 可視性は Mastodon互換で "private" にマップされる。
    assert_eq!(resp["visibility"], "private");
    assert_eq!(
        resp["url"],
        format!("{}/notes/{}", config.server_url(), note_id)
    );
    assert_eq!(resp["actor"]["username"], username);
    assert_eq!(resp["account"]["username"], username);
    assert_eq!(resp["reblog"], serde_json::Value::Null);
    assert_eq!(resp["quote"], serde_json::Value::Null);
    assert_eq!(resp["poll"], serde_json::Value::Null);
    assert_eq!(resp["card"], serde_json::Value::Null);
    assert_eq!(resp["media_attachments"].as_array().unwrap().len(), 0);
    assert_eq!(resp["emojis"].as_array().unwrap().len(), 0);
    assert_eq!(resp["tags"].as_array().unwrap().len(), 0);
    assert_eq!(resp["mentions"].as_array().unwrap().len(), 0);
    assert_eq!(resp["muted"], false);
    assert_eq!(resp["bookmarked"], false);
    assert_eq!(resp["application"], serde_json::Value::Null);
    assert_eq!(resp["language"], serde_json::Value::Null);
    assert_eq!(resp["reblogged"], false);
    assert_eq!(resp["pinned"], false);
}

#[tokio::test]
async fn note_to_response_json_passes_through_reblogged_and_pinned_flags() {
    let (_app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let config = config();
    let actor_id = seed_local_actor(&db, &format!("noteresp4{}", Uuid::new_v4().simple())).await;
    let note_id = seed_note_with_visibility(&db, actor_id, "public", Utc::now()).await;
    let row = fetch_note_render_row(&db, note_id).await.unwrap().unwrap();

    let resp = note_to_response_json(
        &db,
        &config,
        &redis,
        &row,
        &[],
        None,
        None,
        None,
        true,
        true,
    )
    .await
    .unwrap();
    assert_eq!(resp["reblogged"], true);
    assert_eq!(resp["pinned"], true);
}

#[tokio::test]
async fn note_to_response_json_threads_reblog_and_quote_values() {
    let (_app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let config = config();
    let actor_id = seed_local_actor(&db, &format!("noteresp5{}", Uuid::new_v4().simple())).await;
    let note_id = seed_note_with_visibility(&db, actor_id, "public", Utc::now()).await;
    let row = fetch_note_render_row(&db, note_id).await.unwrap().unwrap();

    let fake_reblog = json!({"id": "fake-reblog"});
    let fake_quote = json!({"id": "fake-quote"});
    let resp = note_to_response_json(
        &db,
        &config,
        &redis,
        &row,
        &[],
        None,
        Some(fake_reblog.clone()),
        Some(fake_quote.clone()),
        false,
        false,
    )
    .await
    .unwrap();
    assert_eq!(resp["reblog"], fake_reblog);
    assert_eq!(resp["quote"], fake_quote);
}

#[tokio::test]
async fn note_to_response_json_renders_local_media_attachment() {
    let (_app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let config = config();
    let actor_id = seed_local_actor(&db, &format!("noteresp6{}", Uuid::new_v4().simple())).await;
    let note_id = seed_note_with_visibility(&db, actor_id, "public", Utc::now()).await;
    let s3_key = format!("note-response-test/{}-key.png", Uuid::new_v4().simple());
    let drive_file_id = seed_drive_file(&db, &s3_key, "image/png").await;
    seed_note_attachment(&db, note_id, drive_file_id, 0).await;

    let row = fetch_note_render_row(&db, note_id).await.unwrap().unwrap();
    let resp = note_to_response_json(
        &db,
        &config,
        &redis,
        &row,
        &[],
        None,
        None,
        None,
        false,
        false,
    )
    .await
    .unwrap();

    let attachments = resp["media_attachments"].as_array().unwrap();
    assert_eq!(attachments.len(), 1);
    assert_eq!(attachments[0]["type"], "image");
    assert_eq!(
        attachments[0]["url"],
        format!("{}/{s3_key}", config.media_url())
    );
}

#[tokio::test]
async fn note_to_response_json_renders_remote_media_attachment() {
    let (_app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let config = config();
    let actor_id = seed_local_actor(&db, &format!("noteresp7{}", Uuid::new_v4().simple())).await;
    let note_id = seed_note_with_visibility(&db, actor_id, "public", Utc::now()).await;
    seed_remote_note_attachment(
        &db,
        note_id,
        "https://remote.example/media/pic.jpg",
        "image/jpeg",
        0,
    )
    .await;

    let row = fetch_note_render_row(&db, note_id).await.unwrap().unwrap();
    let resp = note_to_response_json(
        &db,
        &config,
        &redis,
        &row,
        &[],
        None,
        None,
        None,
        false,
        false,
    )
    .await
    .unwrap();

    let attachments = resp["media_attachments"].as_array().unwrap();
    assert_eq!(attachments.len(), 1);
    assert_eq!(attachments[0]["type"], "image");
    assert_eq!(
        attachments[0]["remote_url"],
        "https://remote.example/media/pic.jpg"
    );
}

#[tokio::test]
async fn note_to_response_json_resolves_hashtags() {
    let (_app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let config = config();
    let actor_id = seed_local_actor(&db, &format!("noteresp8{}", Uuid::new_v4().simple())).await;
    let note_id = seed_note_with_visibility(&db, actor_id, "public", Utc::now()).await;
    seed_hashtag_for_note(&db, note_id, &format!("catpics{}", Uuid::new_v4().simple())).await;

    let row = fetch_note_render_row(&db, note_id).await.unwrap().unwrap();
    let resp = note_to_response_json(
        &db,
        &config,
        &redis,
        &row,
        &[],
        None,
        None,
        None,
        false,
        false,
    )
    .await
    .unwrap();

    assert_eq!(resp["tags"].as_array().unwrap().len(), 1);
    assert!(resp["tags"][0]["url"]
        .as_str()
        .unwrap()
        .starts_with(&config.server_url()));
}

#[tokio::test]
async fn note_to_response_json_resolves_content_and_actor_emojis() {
    let (_app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let config = config();
    let actor_id = seed_local_actor(&db, &format!("noteresp9{}", Uuid::new_v4().simple())).await;
    let note_id = seed_note_with_visibility(&db, actor_id, "public", Utc::now()).await;
    let content_shortcode = format!("blobcat{}", Uuid::new_v4().simple());
    let actor_shortcode = format!("partyparrot{}", Uuid::new_v4().simple());
    sqlx::query("UPDATE notes SET content = $1 WHERE id = $2")
        .bind(format!(":{content_shortcode}: hello"))
        .bind(note_id)
        .execute(&db)
        .await
        .unwrap();
    sqlx::query("UPDATE actors SET display_name = $1 WHERE id = $2")
        .bind(format!(":{actor_shortcode}:"))
        .bind(actor_id)
        .execute(&db)
        .await
        .unwrap();
    seed_custom_emoji(
        &db,
        &content_shortcode,
        None,
        "https://local.example/blobcat.png",
    )
    .await;
    seed_custom_emoji(
        &db,
        &actor_shortcode,
        None,
        "https://local.example/parrot.png",
    )
    .await;

    let row = fetch_note_render_row(&db, note_id).await.unwrap().unwrap();
    let resp = note_to_response_json(
        &db,
        &config,
        &redis,
        &row,
        &[],
        None,
        None,
        None,
        false,
        false,
    )
    .await
    .unwrap();

    assert_eq!(resp["emojis"][0]["shortcode"], content_shortcode);
    assert_eq!(resp["emojis"][0]["visible_in_picker"], true);
    assert_eq!(resp["actor"]["emojis"][0]["shortcode"], actor_shortcode);
}

#[tokio::test]
async fn note_to_response_json_resolves_reply_mention() {
    let (_app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let config = config();
    let parent_username = format!("noteresp10p{}", Uuid::new_v4().simple());
    let parent_actor = seed_local_actor(&db, &parent_username).await;
    let parent_note = seed_note_with_visibility(&db, parent_actor, "public", Utc::now()).await;

    let reply_actor =
        seed_local_actor(&db, &format!("noteresp10r{}", Uuid::new_v4().simple())).await;
    let reply_note = seed_note_with_visibility(&db, reply_actor, "public", Utc::now()).await;
    sqlx::query("UPDATE notes SET in_reply_to_id = $1 WHERE id = $2")
        .bind(parent_note)
        .bind(reply_note)
        .execute(&db)
        .await
        .unwrap();

    let row = fetch_note_render_row(&db, reply_note)
        .await
        .unwrap()
        .unwrap();
    let resp = note_to_response_json(
        &db,
        &config,
        &redis,
        &row,
        &[],
        None,
        None,
        None,
        false,
        false,
    )
    .await
    .unwrap();

    assert_eq!(resp["in_reply_to_account_id"], parent_actor.to_string());
    assert_eq!(resp["mentions"].as_array().unwrap().len(), 1);
    assert_eq!(resp["mentions"][0]["username"], parent_username);
}

#[tokio::test]
async fn note_to_response_json_renders_preview_card() {
    let (_app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let config = config();
    let actor_id = seed_local_actor(&db, &format!("noteresp11{}", Uuid::new_v4().simple())).await;
    let note_id = seed_note_with_visibility(&db, actor_id, "public", Utc::now()).await;
    seed_preview_card(&db, note_id, "https://example.com/article", "An Article").await;

    let row = fetch_note_render_row(&db, note_id).await.unwrap().unwrap();
    let resp = note_to_response_json(
        &db,
        &config,
        &redis,
        &row,
        &[],
        None,
        None,
        None,
        false,
        false,
    )
    .await
    .unwrap();

    assert_eq!(resp["card"]["url"], "https://example.com/article");
    assert_eq!(resp["card"]["title"], "An Article");
    assert_eq!(resp["card"]["type"], "link");
}

#[tokio::test]
async fn note_to_response_json_computes_favourited_from_star_reaction() {
    let (_app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let config = config();
    let actor_id = seed_local_actor(&db, &format!("noteresp12{}", Uuid::new_v4().simple())).await;
    let note_id = seed_note_with_visibility(&db, actor_id, "public", Utc::now()).await;
    seed_reaction(&db, note_id, actor_id, "\u{2b50}").await;

    let row = fetch_note_render_row(&db, note_id).await.unwrap().unwrap();
    let reactions = get_reaction_summary(&db, &config, note_id, Some(actor_id))
        .await
        .unwrap();
    let resp = note_to_response_json(
        &db,
        &config,
        &redis,
        &row,
        &reactions,
        Some(actor_id),
        None,
        None,
        false,
        false,
    )
    .await
    .unwrap();

    assert_eq!(resp["favourited"], true);
    assert_eq!(resp["favourites_count"], 1);
}

#[tokio::test]
async fn get_reaction_summary_reports_count_and_me() {
    let (_app, db) = common::test_app_with_db().await;
    let config = config();
    let actor_id = seed_local_actor(&db, &format!("reactor1{}", Uuid::new_v4().simple())).await;
    let other_actor = seed_local_actor(&db, &format!("reactor2{}", Uuid::new_v4().simple())).await;
    let note_id = seed_note_with_visibility(&db, actor_id, "public", Utc::now()).await;
    seed_reaction(&db, note_id, actor_id, "\u{2764}").await;
    seed_reaction(&db, note_id, other_actor, "\u{2764}").await;

    let summary = get_reaction_summary(&db, &config, note_id, Some(actor_id))
        .await
        .unwrap();
    assert_eq!(summary.len(), 1);
    assert_eq!(summary[0]["emoji"], "\u{2764}");
    assert_eq!(summary[0]["count"], 2);
    assert_eq!(summary[0]["me"], true);
    assert_eq!(summary[0]["importable"], false);
}

#[tokio::test]
async fn get_reaction_summary_resolves_local_custom_emoji_url() {
    let (_app, db) = common::test_app_with_db().await;
    let config = config();
    let actor_id = seed_local_actor(&db, &format!("reactor3{}", Uuid::new_v4().simple())).await;
    let note_id = seed_note_with_visibility(&db, actor_id, "public", Utc::now()).await;
    let shortcode = format!("blobcat{}", Uuid::new_v4().simple());
    seed_custom_emoji(&db, &shortcode, None, "https://local.example/blobcat.png").await;
    seed_reaction(&db, note_id, actor_id, &format!(":{shortcode}:")).await;

    let summary = get_reaction_summary(&db, &config, note_id, None)
        .await
        .unwrap();
    assert_eq!(summary.len(), 1);
    assert!(summary[0]["emoji_url"].as_str().is_some());
    assert_eq!(summary[0]["importable"], false);
}

#[tokio::test]
async fn get_reaction_summary_flags_remote_only_emoji_as_importable() {
    let (_app, db) = common::test_app_with_db().await;
    let config = config();
    let actor_id = seed_local_actor(&db, &format!("reactor4{}", Uuid::new_v4().simple())).await;
    let note_id = seed_note_with_visibility(&db, actor_id, "public", Utc::now()).await;
    let domain = format!("remote-reactor{}.example", Uuid::new_v4().simple());
    let shortcode = format!("blobcat{}", Uuid::new_v4().simple());
    seed_custom_emoji(
        &db,
        &shortcode,
        Some(&domain),
        "https://remote.example/blobcat.png",
    )
    .await;
    seed_reaction(&db, note_id, actor_id, &format!(":{shortcode}@{domain}:")).await;

    let summary = get_reaction_summary(&db, &config, note_id, None)
        .await
        .unwrap();
    assert_eq!(summary.len(), 1);
    assert_eq!(summary[0]["importable"], true);
    assert_eq!(summary[0]["import_domain"], domain);
}

#[tokio::test]
async fn get_reaction_summary_plain_unicode_emoji_has_no_url() {
    let (_app, db) = common::test_app_with_db().await;
    let config = config();
    let actor_id = seed_local_actor(&db, &format!("reactor5{}", Uuid::new_v4().simple())).await;
    let note_id = seed_note_with_visibility(&db, actor_id, "public", Utc::now()).await;
    seed_reaction(&db, note_id, actor_id, "\u{1f602}").await;

    let summary = get_reaction_summary(&db, &config, note_id, None)
        .await
        .unwrap();
    assert_eq!(summary.len(), 1);
    assert_eq!(summary[0]["emoji_url"], serde_json::Value::Null);
    assert_eq!(summary[0]["importable"], false);
}

#[tokio::test]
async fn get_poll_data_json_tallies_local_votes() {
    let (_app, db) = common::test_app_with_db().await;
    let actor_id = seed_local_actor(&db, &format!("poll1{}", Uuid::new_v4().simple())).await;
    let voter1 = seed_local_actor(&db, &format!("pollvoter1a{}", Uuid::new_v4().simple())).await;
    let voter2 = seed_local_actor(&db, &format!("pollvoter1b{}", Uuid::new_v4().simple())).await;
    let note_id = seed_note(&db, actor_id, Utc::now()).await;
    let poll_options = json!([{"title": "Cats"}, {"title": "Dogs"}]);
    sqlx::query(
        "UPDATE notes SET is_poll = true, poll_options = $1, poll_multiple = false WHERE id = $2",
    )
    .bind(&poll_options)
    .bind(note_id)
    .execute(&db)
    .await
    .unwrap();
    seed_poll_vote(&db, note_id, voter1, 0).await;
    seed_poll_vote(&db, note_id, voter2, 0).await;

    let data = get_poll_data_json(&db, note_id, &poll_options, None, false, true, Some(voter1))
        .await
        .unwrap();

    assert_eq!(data["votes_count"], 2);
    assert_eq!(data["voters_count"], 2);
    assert_eq!(data["options"][0]["votes_count"], 2);
    assert_eq!(data["options"][1]["votes_count"], 0);
    assert_eq!(data["voted"], true);
    assert_eq!(data["own_votes"], json!([0]));
    assert_eq!(data["expired"], false);
}

#[tokio::test]
async fn get_poll_data_json_detects_expiry() {
    let (_app, db) = common::test_app_with_db().await;
    let actor_id = seed_local_actor(&db, &format!("poll2{}", Uuid::new_v4().simple())).await;
    let note_id = seed_note(&db, actor_id, Utc::now()).await;
    let poll_options = json!([{"title": "A"}]);
    let expires_at = Utc::now() - Duration::hours(1);
    sqlx::query(
        "UPDATE notes SET is_poll = true, poll_options = $1, poll_expires_at = $2 WHERE id = $3",
    )
    .bind(&poll_options)
    .bind(expires_at)
    .bind(note_id)
    .execute(&db)
    .await
    .unwrap();

    let data = get_poll_data_json(
        &db,
        note_id,
        &poll_options,
        Some(expires_at),
        false,
        true,
        None,
    )
    .await
    .unwrap();
    assert_eq!(data["expired"], true);
}

#[tokio::test]
async fn note_to_response_json_renders_poll() {
    let (_app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let config = config();
    let actor_id = seed_local_actor(&db, &format!("noteresp13{}", Uuid::new_v4().simple())).await;
    let note_id = seed_note_with_visibility(&db, actor_id, "public", Utc::now()).await;
    let poll_options = json!([{"title": "Yes"}, {"title": "No"}]);
    sqlx::query("UPDATE notes SET is_poll = true, poll_options = $1 WHERE id = $2")
        .bind(&poll_options)
        .bind(note_id)
        .execute(&db)
        .await
        .unwrap();

    let row = fetch_note_render_row(&db, note_id).await.unwrap().unwrap();
    let resp = note_to_response_json(
        &db,
        &config,
        &redis,
        &row,
        &[],
        None,
        None,
        None,
        false,
        false,
    )
    .await
    .unwrap();

    assert!(!resp["poll"].is_null());
    assert_eq!(resp["poll"]["options"].as_array().unwrap().len(), 2);
    assert_eq!(resp["poll"]["emojis"].as_array().unwrap().len(), 0);
}

#[tokio::test]
async fn note_to_response_json_omits_poll_for_empty_options() {
    let (_app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let config = config();
    let actor_id = seed_local_actor(&db, &format!("noteresp14{}", Uuid::new_v4().simple())).await;
    let note_id = seed_note_with_visibility(&db, actor_id, "public", Utc::now()).await;
    sqlx::query("UPDATE notes SET is_poll = true, poll_options = '[]'::jsonb WHERE id = $1")
        .bind(note_id)
        .execute(&db)
        .await
        .unwrap();

    let row = fetch_note_render_row(&db, note_id).await.unwrap().unwrap();
    let resp = note_to_response_json(
        &db,
        &config,
        &redis,
        &row,
        &[],
        None,
        None,
        None,
        false,
        false,
    )
    .await
    .unwrap();
    assert!(resp["poll"].is_null());
}

#[tokio::test]
async fn note_to_response_json_includes_edited_at_when_updated() {
    let (_app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let config = config();
    let actor_id = seed_local_actor(&db, &format!("noteresp15{}", Uuid::new_v4().simple())).await;
    let note_id = seed_note_with_visibility(&db, actor_id, "public", Utc::now()).await;
    sqlx::query("UPDATE notes SET updated_at = now() WHERE id = $1")
        .bind(note_id)
        .execute(&db)
        .await
        .unwrap();

    let row = fetch_note_render_row(&db, note_id).await.unwrap().unwrap();
    let resp = note_to_response_json(
        &db,
        &config,
        &redis,
        &row,
        &[],
        None,
        None,
        None,
        false,
        false,
    )
    .await
    .unwrap();
    assert!(resp["edited_at"].is_string());
}

#[tokio::test]
async fn note_to_response_json_reads_cached_remote_software_info() {
    let (_app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let config = config();
    let domain = format!("remote-software{}.example", Uuid::new_v4().simple());
    let actor_id = seed_remote_actor(&db, "remoteauthor", &domain).await;
    let note_id = seed_note_with_visibility(&db, actor_id, "public", Utc::now()).await;

    {
        use redis::AsyncCommands;
        let mut conn = redis.clone();
        let _: () = conn
            .set(format!("nodeinfo:software:{domain}"), "mastodon")
            .await
            .unwrap();
        let _: () = conn
            .set(format!("nodeinfo:software_version:{domain}"), "4.2.0")
            .await
            .unwrap();
        let _: () = conn
            .set(format!("nodeinfo:instance_name:{domain}"), "")
            .await
            .unwrap();
    }

    let row = fetch_note_render_row(&db, note_id).await.unwrap().unwrap();
    let resp = note_to_response_json(
        &db,
        &config,
        &redis,
        &row,
        &[],
        None,
        None,
        None,
        false,
        false,
    )
    .await
    .unwrap();

    assert_eq!(resp["actor"]["server_software"], "mastodon");
    assert_eq!(resp["actor"]["server_software_version"], "4.2.0");
    assert_eq!(resp["actor"]["server_name"], serde_json::Value::Null);
}

#[tokio::test]
async fn note_to_response_json_leaves_software_info_null_on_cache_miss() {
    let (_app, db) = common::test_app_with_db().await;
    let redis = connect_redis().await;
    let config = config();
    let domain = format!("uncached-software{}.example", Uuid::new_v4().simple());
    let actor_id = seed_remote_actor(&db, "remoteauthor2", &domain).await;
    let note_id = seed_note_with_visibility(&db, actor_id, "public", Utc::now()).await;

    let row = fetch_note_render_row(&db, note_id).await.unwrap().unwrap();
    let resp = note_to_response_json(
        &db,
        &config,
        &redis,
        &row,
        &[],
        None,
        None,
        None,
        false,
        false,
    )
    .await
    .unwrap();

    assert_eq!(resp["actor"]["server_software"], serde_json::Value::Null);
}
