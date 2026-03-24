"""Render Python objects to ActivityPub JSON-LD."""

from datetime import datetime

from app.activitypub import resolve_source_media_type
from app.config import settings
from app.models.actor import Actor
from app.models.note import Note
from app.services.actor_service import actor_uri


def _iso_z(dt: datetime) -> str:
    """Format datetime as ISO 8601 with Z suffix (no +00:00)."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


AP_CONTEXT = [
    "https://www.w3.org/ns/activitystreams",
    "https://w3id.org/security/v1",
    {
        "misskey": "https://misskey-hub.net/ns#",
        "toot": "http://joinmastodon.org/ns#",
        "Emoji": "toot:Emoji",
        "schema": "http://schema.org#",
        "value": "schema:value",
        "discoverable": "toot:discoverable",
        "manuallyApprovesFollowers": "as:manuallyApprovesFollowers",
        "vcard": "http://www.w3.org/2006/vcard/ns#",
        "PropertyValue": "schema:PropertyValue",
        "isCat": "misskey:isCat",
        "_misskey_reaction": "misskey:_misskey_reaction",
        "_misskey_content": "misskey:_misskey_content",
        "_misskey_quote": "misskey:_misskey_quote",
        "_misskey_talk": "misskey:_misskey_talk",
        "_misskey_license": "misskey:_misskey_license",
        "_misskey_requireSigninToViewContents": "misskey:_misskey_requireSigninToViewContents",
        "_misskey_makeNotesFollowersOnlyBefore": "misskey:_misskey_makeNotesFollowersOnlyBefore",
        "_misskey_makeNotesHiddenBefore": "misskey:_misskey_makeNotesHiddenBefore",
        "quoteUrl": "as:quoteUrl",
        "votersCount": "toot:votersCount",
        "featured": {"@id": "toot:featured", "@type": "@id"},
        "movedTo": {"@id": "as:movedTo", "@type": "@id"},
        "alsoKnownAs": {"@id": "as:alsoKnownAs", "@type": "@id"},
    },
]

AP_PUBLIC = "https://www.w3.org/ns/activitystreams#Public"


def render_actor(actor: Actor) -> dict:
    # For local actors, always derive URLs from server_url to ensure correct scheme
    if actor.domain is None:
        actor_url = f"{settings.server_url}/users/{actor.username}"
        inbox = f"{actor_url}/inbox"
        outbox = f"{actor_url}/outbox"
        followers = f"{actor_url}/followers"
        following = f"{actor_url}/following"
        shared_inbox = f"{settings.server_url}/inbox"
    else:
        actor_url = actor.ap_id
        inbox = actor.inbox_url
        outbox = actor.outbox_url
        followers = actor.followers_url
        following = actor.following_url
        shared_inbox = actor.shared_inbox_url

    data = {
        "@context": AP_CONTEXT,
        "id": actor_url,
        "type": actor.type,
        "preferredUsername": actor.username,
        "name": actor.display_name or actor.username,
        "inbox": inbox,
        "outbox": outbox,
        "url": f"{settings.server_url}/@{actor.username}" if actor.domain is None else actor.ap_id,
        "published": _iso_z(actor.created_at) if actor.created_at else None,
        "manuallyApprovesFollowers": actor.manually_approves_followers,
        "discoverable": actor.discoverable,
        "publicKey": {
            "id": f"{actor_url}#main-key",
            "owner": actor_url,
            "publicKeyPem": actor.public_key_pem,
        },
        "endpoints": {
            "sharedInbox": shared_inbox or f"{settings.server_url}/inbox",
        },
        "isCat": actor.is_cat,
    }

    if actor.summary:
        data["summary"] = actor.summary
    if actor.avatar_url:
        data["icon"] = {"type": "Image", "url": actor.avatar_url}
    if actor.header_url:
        data["image"] = {"type": "Image", "url": actor.header_url}
    if followers:
        data["followers"] = followers
    if following:
        data["following"] = following
    if getattr(actor, "is_local", False):
        data["featured"] = f"{settings.server_url}/users/{actor.username}/featured"
    elif getattr(actor, "featured_url", None):
        data["featured"] = actor.featured_url
    if actor.fields:
        data["attachment"] = [
            {
                "type": "PropertyValue",
                "name": field.get("name", ""),
                "value": field.get("value", ""),
            }
            for field in actor.fields
        ]
    if getattr(actor, "birthday", None):
        data["vcard:bday"] = actor.birthday.isoformat()
    if getattr(actor, "moved_to_ap_id", None):
        data["movedTo"] = actor.moved_to_ap_id
    if getattr(actor, "also_known_as", None):
        data["alsoKnownAs"] = actor.also_known_as
    if getattr(actor, "require_signin_to_view", False):
        data["_misskey_requireSigninToViewContents"] = True
    if getattr(actor, "make_notes_followers_only_before", None) is not None:
        data["_misskey_makeNotesFollowersOnlyBefore"] = actor.make_notes_followers_only_before
    if getattr(actor, "make_notes_hidden_before", None) is not None:
        data["_misskey_makeNotesHiddenBefore"] = actor.make_notes_hidden_before

    return data


def render_note(note: Note) -> dict:
    actor = note.actor
    note_type = "Question" if getattr(note, "is_poll", False) else "Note"
    data = {
        "@context": AP_CONTEXT,
        "id": note.ap_id,
        "type": note_type,
        "attributedTo": actor_uri(actor),
        "content": note.content,
        "published": _iso_z(note.published),
        "to": note.to,
        "cc": note.cc,
        "url": f"{settings.server_url}/notes/{note.id}",
    }

    if getattr(note, "updated_at", None):
        data["updated"] = _iso_z(note.updated_at)
    if note.source:
        user = getattr(note.actor, "local_user", None)
        prefs = user.preferences if user else None
        media_type = resolve_source_media_type(note.source, prefs)
        data["source"] = {"content": note.source, "mediaType": media_type}
        data["_misskey_content"] = note.source
    if note.sensitive:
        data["sensitive"] = True
    if note.spoiler_text:
        data["summary"] = note.spoiler_text
    if note.in_reply_to_ap_id:
        data["inReplyTo"] = note.in_reply_to_ap_id

    # Quote renote
    if hasattr(note, "quote_ap_id") and note.quote_ap_id:
        data["_misskey_quote"] = note.quote_ap_id
        data["quoteUrl"] = note.quote_ap_id

    # Attachments
    if hasattr(note, "attachments") and note.attachments:
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
                if att.drive_file.focal_x is not None and att.drive_file.focal_y is not None:
                    doc["focalPoint"] = [att.drive_file.focal_x, att.drive_file.focal_y]
                attachment_list.append(doc)
            elif att.remote_url:
                attachment_list.append(
                    {
                        "type": "Document",
                        "mediaType": att.remote_mime_type or "application/octet-stream",
                        "url": att.remote_url,
                        "name": att.remote_description or att.remote_name or "",
                    }
                )
        if attachment_list:
            data["attachment"] = attachment_list

    # Tags (mentions + emoji)
    tag = []
    if hasattr(note, "mentions") and note.mentions:
        for m in note.mentions:
            name = f"@{m['username']}@{m['domain']}" if m.get("domain") else f"@{m['username']}"
            tag.append(
                {
                    "type": "Mention",
                    "href": m["ap_id"],
                    "name": name,
                }
            )

    # Hashtag tags
    if hasattr(note, "_hashtag_names") and note._hashtag_names:
        for ht_name in note._hashtag_names:
            tag.append(
                {
                    "type": "Hashtag",
                    "href": f"{settings.server_url}/tags/{ht_name}",
                    "name": f"#{ht_name}",
                }
            )

    # Custom emoji tags
    if hasattr(note, "_emoji_tags") and note._emoji_tags:
        for e in note._emoji_tags:
            # Guess media type from URL extension
            url = e["url"]
            ext = url.rsplit(".", 1)[-1].lower() if "." in url else "png"
            media_type = {
                "png": "image/png",
                "jpg": "image/jpeg",
                "jpeg": "image/jpeg",
                "gif": "image/gif",
                "webp": "image/webp",
                "avif": "image/avif",
                "svg": "image/svg+xml",
            }.get(ext, "image/png")

            emoji_tag: dict = {
                "id": f"{settings.server_url}/emojis/{e['shortcode']}",
                "type": "Emoji",
                "name": f":{e['shortcode']}:",
                "icon": {"type": "Image", "mediaType": media_type, "url": url},
            }
            # Misskey-compatible license
            if e.get("license"):
                emoji_tag["_misskey_license"] = {"freeText": e["license"]}
                emoji_tag["license"] = e["license"]
            # CherryPick / extended fields
            if e.get("aliases"):
                emoji_tag["keywords"] = e["aliases"]
            if e.get("is_sensitive"):
                emoji_tag["isSensitive"] = True
            if e.get("author"):
                emoji_tag["author"] = e["author"]
            if e.get("description"):
                emoji_tag["description"] = e["description"]
            if e.get("copy_permission"):
                emoji_tag["copyPermission"] = e["copy_permission"]
            if e.get("usage_info"):
                emoji_tag["usageInfo"] = e["usage_info"]
            if e.get("is_based_on"):
                emoji_tag["isBasedOn"] = e["is_based_on"]
            if e.get("category"):
                emoji_tag["category"] = e["category"]
            tag.append(emoji_tag)

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
            data["endTime"] = _iso_z(note.poll_expires_at)
        total_votes = sum(opt.get("votes_count", 0) for opt in note.poll_options)
        data["votersCount"] = total_votes

    # Misskey talk flag
    if getattr(note, "is_talk", False):
        data["_misskey_talk"] = True

    return data


def render_vote_activity(poll_note: Note, voter: Actor, option_name: str) -> dict:
    """Render a vote on a remote poll as Create(Note) with name field."""
    import uuid as _uuid

    vote_id = f"{actor_uri(voter)}#vote-{_uuid.uuid4().hex[:8]}"
    note_object = {
        "type": "Note",
        "id": vote_id,
        "attributedTo": actor_uri(voter),
        "to": poll_note.actor.ap_id if poll_note.actor else "",
        "inReplyTo": poll_note.ap_id,
        "name": option_name,
    }
    return {
        "@context": AP_CONTEXT,
        "id": f"{vote_id}/activity",
        "type": "Create",
        "actor": actor_uri(voter),
        "object": note_object,
        "to": [poll_note.actor.ap_id] if poll_note.actor else [],
    }


def render_poll_update_activity(note: Note) -> dict:
    """Render an Update(Question) activity for a local poll (vote count update)."""
    import uuid as _uuid

    activity_id = f"{note.ap_id}#update-{_uuid.uuid4().hex[:8]}"
    return render_update_activity(activity_id, actor_uri(note.actor), render_note(note))


def render_create_activity(note: Note) -> dict:
    return {
        "@context": AP_CONTEXT,
        "id": f"{note.ap_id}/activity",
        "type": "Create",
        "actor": actor_uri(note.actor),
        "object": render_note(note),
        "to": note.to,
        "cc": note.cc,
        "published": _iso_z(note.published),
    }


def render_like_activity(activity_id: str, actor_ap_id: str, note_ap_id: str, emoji: str) -> dict:
    """Render a Like activity.

    For ⭐ (favourite): standard AP Like without content (all servers understand).
    For other emoji: Like with content + _misskey_reaction (Misskey format).
    """
    activity: dict = {
        "@context": AP_CONTEXT,
        "id": activity_id,
        "type": "Like",
        "actor": actor_ap_id,
        "object": note_ap_id,
    }
    if emoji != "\u2b50":
        activity["content"] = emoji
        activity["_misskey_reaction"] = emoji
    return activity


def render_emoji_react_activity(
    activity_id: str, actor_ap_id: str, note_ap_id: str, emoji: str
) -> dict:
    """Render an EmojiReact activity (Fedibird/Pleroma/Akkoma compatible)."""
    return {
        "@context": AP_CONTEXT,
        "id": activity_id,
        "type": "EmojiReact",
        "actor": actor_ap_id,
        "object": note_ap_id,
        "content": emoji,
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


def render_reject_activity(activity_id: str, actor_ap_id: str, follow_activity: dict) -> dict:
    return {
        "@context": AP_CONTEXT,
        "id": activity_id,
        "type": "Reject",
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
