"""Render Python objects to ActivityPub JSON-LD."""

from app.config import settings
from app.models.actor import Actor
from app.models.note import Note

AP_CONTEXT = [
    "https://www.w3.org/ns/activitystreams",
    "https://w3id.org/security/v1",
    {
        "misskey": "https://misskey-hub.net/ns#",
        "toot": "http://joinmastodon.org/ns#",
        "schema": "http://schema.org#",
        "value": "schema:value",
        "discoverable": "toot:discoverable",
        "manuallyApprovesFollowers": "as:manuallyApprovesFollowers",
        "isCat": "misskey:isCat",
        "_misskey_reaction": "misskey:_misskey_reaction",
        "_misskey_content": "misskey:_misskey_content",
        "_misskey_quote": "misskey:_misskey_quote",
        "_misskey_talk": "misskey:_misskey_talk",
        "quoteUrl": "as:quoteUrl",
        "votersCount": "toot:votersCount",
        "featured": {"@id": "toot:featured", "@type": "@id"},
        "movedTo": {"@id": "as:movedTo", "@type": "@id"},
        "alsoKnownAs": {"@id": "as:alsoKnownAs", "@type": "@id"},
    },
]

AP_PUBLIC = "https://www.w3.org/ns/activitystreams#Public"


def render_actor(actor: Actor) -> dict:
    data = {
        "@context": AP_CONTEXT,
        "id": actor.ap_id,
        "type": actor.type,
        "preferredUsername": actor.username,
        "name": actor.display_name or actor.username,
        "inbox": actor.inbox_url,
        "outbox": actor.outbox_url,
        "url": f"{settings.server_url}/@{actor.username}",
        "published": actor.created_at.isoformat() + "Z" if actor.created_at else None,
        "manuallyApprovesFollowers": actor.manually_approves_followers,
        "discoverable": actor.discoverable,
        "publicKey": {
            "id": f"{actor.ap_id}#main-key",
            "owner": actor.ap_id,
            "publicKeyPem": actor.public_key_pem,
        },
        "endpoints": {
            "sharedInbox": actor.shared_inbox_url or f"{settings.server_url}/inbox",
        },
        "isCat": actor.is_cat,
    }

    if actor.summary:
        data["summary"] = actor.summary
    if actor.avatar_url:
        data["icon"] = {"type": "Image", "url": actor.avatar_url}
    if actor.header_url:
        data["image"] = {"type": "Image", "url": actor.header_url}
    if actor.followers_url:
        data["followers"] = actor.followers_url
    if actor.following_url:
        data["following"] = actor.following_url
    if getattr(actor, "is_local", False):
        data["featured"] = f"{settings.server_url}/users/{actor.username}/featured"
    elif getattr(actor, "featured_url", None):
        data["featured"] = actor.featured_url
    if getattr(actor, "moved_to_ap_id", None):
        data["movedTo"] = actor.moved_to_ap_id
    if getattr(actor, "also_known_as", None):
        data["alsoKnownAs"] = actor.also_known_as

    return data


def render_note(note: Note) -> dict:
    actor = note.actor
    note_type = "Question" if getattr(note, "is_poll", False) else "Note"
    data = {
        "@context": AP_CONTEXT,
        "id": note.ap_id,
        "type": note_type,
        "attributedTo": actor.ap_id,
        "content": note.content,
        "published": note.published.isoformat() + "Z",
        "to": note.to,
        "cc": note.cc,
        "url": f"{settings.server_url}/notes/{note.id}",
    }

    if note.source:
        data["source"] = {"content": note.source, "mediaType": "text/plain"}
        data["_misskey_content"] = note.source
    if note.sensitive:
        data["sensitive"] = True
    if note.spoiler_text:
        data["summary"] = note.spoiler_text
    if note.in_reply_to_ap_id:
        data["inReplyTo"] = note.in_reply_to_ap_id

    # Quote renote
    if hasattr(note, 'quote_ap_id') and note.quote_ap_id:
        data["_misskey_quote"] = note.quote_ap_id
        data["quoteUrl"] = note.quote_ap_id

    # Attachments
    if hasattr(note, 'attachments') and note.attachments:
        attachment_list = []
        for att in note.attachments:
            if att.drive_file:
                from app.services.drive_service import file_to_url
                url = file_to_url(att.drive_file)
                doc = {
                    "type": "Document",
                    "mediaType": att.drive_file.mime_type,
                    "url": url,
                    "name": att.drive_file.description or att.drive_file.filename,
                }
                if att.drive_file.width and att.drive_file.height:
                    doc["width"] = att.drive_file.width
                    doc["height"] = att.drive_file.height
                if att.drive_file.blurhash:
                    doc["blurhash"] = att.drive_file.blurhash
                attachment_list.append(doc)
            elif att.remote_url:
                attachment_list.append({
                    "type": "Document",
                    "mediaType": att.remote_mime_type or "application/octet-stream",
                    "url": att.remote_url,
                    "name": att.remote_description or att.remote_name or "",
                })
        if attachment_list:
            data["attachment"] = attachment_list

    # Tags (mentions)
    tag = []
    if hasattr(note, 'mentions') and note.mentions:
        for m in note.mentions:
            name = f"@{m['username']}@{m['domain']}" if m.get("domain") else f"@{m['username']}"
            tag.append({
                "type": "Mention",
                "href": m["ap_id"],
                "name": name,
            })
    if tag:
        data["tag"] = tag

    # Poll (Question type)
    if getattr(note, "is_poll", False) and getattr(note, "poll_options", None):
        choices_key = "anyOf" if note.poll_multiple else "oneOf"
        data[choices_key] = [
            {
                "type": "Note",
                "name": opt.get("title", ""),
                "replies": {
                    "type": "Collection",
                    "totalItems": opt.get("votes_count", 0),
                },
            }
            for opt in note.poll_options
        ]
        if getattr(note, "poll_expires_at", None):
            data["endTime"] = note.poll_expires_at.isoformat() + "Z"
        total_votes = sum(opt.get("votes_count", 0) for opt in note.poll_options)
        data["votersCount"] = total_votes

    # Misskey talk flag
    if getattr(note, "is_talk", False):
        data["_misskey_talk"] = True

    return data


def render_create_activity(note: Note) -> dict:
    return {
        "@context": AP_CONTEXT,
        "id": f"{note.ap_id}/activity",
        "type": "Create",
        "actor": note.actor.ap_id,
        "object": render_note(note),
        "to": note.to,
        "cc": note.cc,
        "published": note.published.isoformat() + "Z",
    }


def render_like_activity(
    activity_id: str, actor_ap_id: str, note_ap_id: str, emoji: str
) -> dict:
    """Render a Like activity with Misskey-compatible emoji reaction."""
    return {
        "@context": AP_CONTEXT,
        "id": activity_id,
        "type": "Like",
        "actor": actor_ap_id,
        "object": note_ap_id,
        "content": emoji,
        "_misskey_reaction": emoji,
    }


def render_follow_activity(activity_id: str, actor_ap_id: str, target_ap_id: str) -> dict:
    return {
        "@context": AP_CONTEXT,
        "id": activity_id,
        "type": "Follow",
        "actor": actor_ap_id,
        "object": target_ap_id,
    }


def render_accept_activity(activity_id: str, actor_ap_id: str, follow_activity: dict) -> dict:
    return {
        "@context": AP_CONTEXT,
        "id": activity_id,
        "type": "Accept",
        "actor": actor_ap_id,
        "object": follow_activity,
    }


def render_undo_activity(activity_id: str, actor_ap_id: str, inner_activity: dict) -> dict:
    return {
        "@context": AP_CONTEXT,
        "id": activity_id,
        "type": "Undo",
        "actor": actor_ap_id,
        "object": inner_activity,
    }


def render_delete_activity(activity_id: str, actor_ap_id: str, object_id: str) -> dict:
    return {
        "@context": AP_CONTEXT,
        "id": activity_id,
        "type": "Delete",
        "actor": actor_ap_id,
        "object": {"id": object_id, "type": "Tombstone"},
    }


def render_announce_activity(
    activity_id: str,
    actor_ap_id: str,
    note_ap_id: str,
    to: list[str],
    cc: list[str],
    published: str,
) -> dict:
    return {
        "@context": AP_CONTEXT,
        "id": activity_id,
        "type": "Announce",
        "actor": actor_ap_id,
        "object": note_ap_id,
        "to": to,
        "cc": cc,
        "published": published,
    }


def render_update_activity(activity_id: str, actor_ap_id: str, object_data: dict) -> dict:
    return {
        "@context": AP_CONTEXT,
        "id": activity_id,
        "type": "Update",
        "actor": actor_ap_id,
        "object": object_data,
    }


def render_ordered_collection(collection_id: str, total_items: int, first_page: str) -> dict:
    return {
        "@context": "https://www.w3.org/ns/activitystreams",
        "id": collection_id,
        "type": "OrderedCollection",
        "totalItems": total_items,
        "first": first_page,
    }


def render_block_activity(activity_id: str, actor_ap_id: str, target_ap_id: str) -> dict:
    return {
        "@context": AP_CONTEXT,
        "id": activity_id,
        "type": "Block",
        "actor": actor_ap_id,
        "object": target_ap_id,
    }


def render_flag_activity(
    activity_id: str,
    actor_ap_id: str,
    target_actor_ap_id: str,
    note_ap_ids: list[str] | None = None,
    content: str = "",
) -> dict:
    """Render a Flag (report) activity for federation."""
    obj = [target_actor_ap_id]
    if note_ap_ids:
        obj.extend(note_ap_ids)
    return {
        "@context": AP_CONTEXT,
        "id": activity_id,
        "type": "Flag",
        "actor": actor_ap_id,
        "object": obj,
        "content": content,
    }


def render_move_activity(activity_id: str, actor_ap_id: str, target_ap_id: str) -> dict:
    return {
        "@context": AP_CONTEXT,
        "id": activity_id,
        "type": "Move",
        "actor": actor_ap_id,
        "object": actor_ap_id,
        "target": target_ap_id,
    }


def render_add_activity(activity_id: str, actor_ap_id: str, object_id: str, target: str) -> dict:
    return {
        "@context": AP_CONTEXT,
        "id": activity_id,
        "type": "Add",
        "actor": actor_ap_id,
        "object": object_id,
        "target": target,
    }


def render_remove_activity(activity_id: str, actor_ap_id: str, object_id: str, target: str) -> dict:
    return {
        "@context": AP_CONTEXT,
        "id": activity_id,
        "type": "Remove",
        "actor": actor_ap_id,
        "object": object_id,
        "target": target,
    }


def render_ordered_collection_page(
    page_id: str,
    part_of: str,
    items: list[dict],
    next_page: str | None = None,
) -> dict:
    data = {
        "@context": "https://www.w3.org/ns/activitystreams",
        "id": page_id,
        "type": "OrderedCollectionPage",
        "partOf": part_of,
        "orderedItems": items,
    }
    if next_page:
        data["next"] = next_page
    return data
