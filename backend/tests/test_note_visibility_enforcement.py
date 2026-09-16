"""閲覧権限のないノートが各経路から取得・操作できないことの回帰テスト。"""

from sqlalchemy import select

from app.models.bookmark import Bookmark
from app.models.follow import Follow
from app.models.note import Note
from app.models.pinned_note import PinnedNote
from app.models.poll_vote import PollVote
from app.models.reaction import Reaction
from app.services.note_service import filter_visible_notes
from tests.conftest import make_note


async def _follow(db, follower, target) -> Follow:
    follow = Follow(follower_id=follower.actor_id, following_id=target.actor_id, accepted=True)
    db.add(follow)
    await db.flush()
    return follow


async def _make_poll(db, actor, visibility: str) -> Note:
    note = await make_note(db, actor, content="poll", visibility=visibility)
    note.is_poll = True
    note.poll_options = [{"title": "A", "votes_count": 0}, {"title": "B", "votes_count": 0}]
    await db.flush()
    return note


# ── filter_visible_notes ─────────────────────────────────────────────────


async def test_filter_visible_notes_mixed(db, mock_valkey, test_user, test_user_b):
    public = await make_note(db, test_user_b.actor, visibility="public")
    followers = await make_note(db, test_user_b.actor, visibility="followers")
    dm_other = await make_note(db, test_user_b.actor, visibility="direct")
    dm_to_me = await make_note(db, test_user_b.actor, visibility="direct")
    dm_to_me.mentions = [{"ap_id": test_user.actor.ap_id, "username": "testuser"}]
    own_dm = await make_note(db, test_user.actor, visibility="direct")
    await db.flush()
    notes = [public, followers, dm_other, dm_to_me, own_dm]

    visible = await filter_visible_notes(db, notes, test_user.actor_id)
    assert [n.id for n in visible] == [public.id, dm_to_me.id, own_dm.id]

    await _follow(db, test_user, test_user_b)
    visible = await filter_visible_notes(db, notes, test_user.actor_id)
    assert [n.id for n in visible] == [public.id, followers.id, dm_to_me.id, own_dm.id]

    anon = await filter_visible_notes(db, notes, None)
    assert [n.id for n in anon] == [public.id]


# ── AP featured ──────────────────────────────────────────────────────────


async def test_featured_excludes_non_public_pins(app_client, db, mock_valkey, test_user):
    public = await make_note(db, test_user.actor, content="public pin", visibility="public")
    unlisted = await make_note(db, test_user.actor, content="unlisted pin", visibility="unlisted")
    followers = await make_note(db, test_user.actor, content="secret pin", visibility="followers")
    for pos, note in enumerate([followers, public, unlisted]):
        db.add(PinnedNote(actor_id=test_user.actor_id, note_id=note.id, position=pos))
    await db.flush()

    resp = await app_client.get(
        "/users/testuser/featured", headers={"Accept": "application/activity+json"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["totalItems"] == 2
    assert [item["id"] for item in data["orderedItems"]] == [public.ap_id, unlisted.ap_id]
    assert "secret pin" not in resp.text


async def test_pin_direct_note_rejected(authed_client, db, mock_valkey, test_user):
    note = await make_note(db, test_user.actor, visibility="direct")
    resp = await authed_client.post(f"/api/v1/statuses/{note.id}/pin")
    assert resp.status_code == 422
    rows = await db.execute(select(PinnedNote).where(PinnedNote.note_id == note.id))
    assert rows.scalar_one_or_none() is None


async def test_pin_followers_note_allowed(authed_client, db, mock_valkey, test_user):
    note = await make_note(db, test_user.actor, visibility="followers")
    resp = await authed_client.post(f"/api/v1/statuses/{note.id}/pin")
    assert resp.status_code == 200


# ── リアクション / ブックマーク ─────────────────────────────────────────


async def test_react_to_invisible_note_404(
    authed_client, db, mock_valkey, test_user, test_user_b
):
    note = await make_note(db, test_user_b.actor, visibility="direct")
    resp = await authed_client.post(f"/api/v1/statuses/{note.id}/react/👍")
    assert resp.status_code == 404
    rows = await db.execute(select(Reaction).where(Reaction.note_id == note.id))
    assert rows.scalars().all() == []


async def test_bookmark_invisible_note_404(
    authed_client, db, mock_valkey, test_user, test_user_b
):
    note = await make_note(db, test_user_b.actor, visibility="followers")
    resp = await authed_client.post(f"/api/v1/statuses/{note.id}/bookmark")
    assert resp.status_code == 404
    rows = await db.execute(select(Bookmark).where(Bookmark.note_id == note.id))
    assert rows.scalar_one_or_none() is None


async def test_bookmark_followers_note_as_follower(
    authed_client, db, mock_valkey, test_user, test_user_b
):
    await _follow(db, test_user, test_user_b)
    note = await make_note(db, test_user_b.actor, visibility="followers")
    resp = await authed_client.post(f"/api/v1/statuses/{note.id}/bookmark")
    assert resp.status_code == 200


async def test_bookmarks_list_hides_no_longer_visible(
    authed_client, db, mock_valkey, test_user, test_user_b
):
    follow = await _follow(db, test_user, test_user_b)
    public = await make_note(db, test_user_b.actor, content="open note", visibility="public")
    private = await make_note(db, test_user_b.actor, content="fo note", visibility="followers")
    db.add_all([
        Bookmark(actor_id=test_user.actor_id, note_id=public.id),
        Bookmark(actor_id=test_user.actor_id, note_id=private.id),
    ])
    await db.flush()

    resp = await authed_client.get("/api/v1/bookmarks")
    assert {n["id"] for n in resp.json()} == {str(public.id), str(private.id)}

    await db.delete(follow)
    await db.flush()
    resp = await authed_client.get("/api/v1/bookmarks")
    assert resp.status_code == 200
    assert [n["id"] for n in resp.json()] == [str(public.id)]


async def test_favourites_list_hides_invisible(
    authed_client, db, mock_valkey, test_user, test_user_b
):
    public = await make_note(db, test_user_b.actor, visibility="public")
    dm = await make_note(db, test_user_b.actor, content="dm body", visibility="direct")
    db.add_all([
        Reaction(actor_id=test_user.actor_id, note_id=public.id, emoji="⭐"),
        Reaction(actor_id=test_user.actor_id, note_id=dm.id, emoji="⭐"),
    ])
    await db.flush()

    resp = await authed_client.get("/api/v1/favourites")
    assert resp.status_code == 200
    assert [n["id"] for n in resp.json()] == [str(public.id)]
    assert "dm body" not in resp.text


# ── 引用 / 返信 ──────────────────────────────────────────────────────────


async def test_quote_invisible_note_ignored(
    authed_client, db, mock_valkey, test_user, test_user_b
):
    """見えないノートの引用は存在しない引用先と同様に無視される。"""
    dm = await make_note(db, test_user_b.actor, content="dm secret", visibility="direct")
    resp = await authed_client.post(
        "/api/v1/statuses",
        json={"content": "quoting", "visibility": "public", "quote_id": str(dm.id)},
    )
    assert resp.status_code == 201
    assert resp.json()["quote"] is None
    assert "dm secret" not in resp.text
    rows = await db.execute(select(Note).where(Note.quote_id == dm.id))
    assert rows.scalars().all() == []


async def test_reply_to_invisible_note_404(
    authed_client, db, mock_valkey, test_user, test_user_b
):
    dm = await make_note(db, test_user_b.actor, visibility="direct")
    resp = await authed_client.post(
        "/api/v1/statuses",
        json={"content": "reply", "visibility": "public", "in_reply_to_id": str(dm.id)},
    )
    assert resp.status_code == 404


async def test_quote_of_invisible_note_not_embedded(
    app_client, db, mock_valkey, test_user, test_user_b
):
    """既に存在する引用 (連合経由など) でも、見えない引用先は埋め込まない。"""
    dm = await make_note(db, test_user_b.actor, content="dm secret", visibility="direct")
    public_quote = await make_note(db, test_user.actor, content="look", visibility="public")
    public_quote.quote_id = dm.id
    public_quote.quote_ap_id = dm.ap_id
    visible_target = await make_note(db, test_user_b.actor, content="open", visibility="public")
    public_quote2 = await make_note(db, test_user.actor, content="look2", visibility="public")
    public_quote2.quote_id = visible_target.id
    await db.flush()

    resp = await app_client.get(f"/api/v1/statuses/{public_quote.id}")
    assert resp.status_code == 200
    assert resp.json()["quote"] is None
    assert "dm secret" not in resp.text

    resp = await app_client.get(f"/api/v1/statuses/{public_quote2.id}")
    assert resp.status_code == 200
    assert resp.json()["quote"]["id"] == str(visible_target.id)


# ── 投票 ─────────────────────────────────────────────────────────────────


async def test_get_invisible_poll_404(authed_client, db, mock_valkey, test_user, test_user_b):
    poll = await _make_poll(db, test_user_b.actor, "followers")
    resp = await authed_client.get(f"/api/v1/polls/{poll.id}")
    assert resp.status_code == 404


async def test_vote_invisible_poll_404(authed_client, db, mock_valkey, test_user, test_user_b):
    poll = await _make_poll(db, test_user_b.actor, "followers")
    resp = await authed_client.post(f"/api/v1/polls/{poll.id}/votes", json={"choices": [0]})
    assert resp.status_code == 404
    rows = await db.execute(select(PollVote).where(PollVote.note_id == poll.id))
    assert rows.scalars().all() == []


async def test_vote_followers_poll_as_follower(
    authed_client, db, mock_valkey, test_user, test_user_b
):
    await _follow(db, test_user, test_user_b)
    poll = await _make_poll(db, test_user_b.actor, "followers")
    resp = await authed_client.post(f"/api/v1/polls/{poll.id}/votes", json={"choices": [1]})
    assert resp.status_code == 200
    assert resp.json()["own_votes"] == [1]
    assert resp.json()["votes_count"] == 1
