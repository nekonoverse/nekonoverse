"""Tests for Flag (report) activity handler."""

from sqlalchemy import select

from app.models.report import Report
from tests.conftest import make_note, make_remote_actor


async def test_handle_flag_creates_report(db, test_user, mock_valkey):
    """Incoming Flag activity should create a report against the local actor."""
    from app.activitypub.handlers.flag import handle_flag

    reporter = await make_remote_actor(db, username="reporter", domain="reporter.example")
    activity = {
        "type": "Flag",
        "id": "http://reporter.example/activities/flag1",
        "actor": reporter.ap_id,
        "object": [test_user.actor.ap_id],
        "content": "Spam account",
    }
    await handle_flag(db, activity)

    result = await db.execute(
        select(Report).where(Report.target_actor_id == test_user.actor_id)
    )
    report = result.scalar_one_or_none()
    assert report is not None
    assert report.reporter_actor_id == reporter.id
    assert report.comment == "Spam account"
    assert report.target_note_id is None


async def test_handle_flag_with_note(db, test_user, mock_valkey):
    """Flag with actor + note should set target_note_id."""
    from app.activitypub.handlers.flag import handle_flag

    reporter = await make_remote_actor(db, username="rep2", domain="rep2.example")
    note = await make_note(db, test_user.actor, content="Bad post")
    activity = {
        "type": "Flag",
        "id": "http://rep2.example/activities/flag2",
        "actor": reporter.ap_id,
        "object": [test_user.actor.ap_id, note.ap_id],
        "content": "Offensive content",
    }
    await handle_flag(db, activity)

    result = await db.execute(
        select(Report).where(Report.reporter_actor_id == reporter.id)
    )
    report = result.scalar_one_or_none()
    assert report is not None
    assert report.target_note_id == note.id
    assert report.comment == "Offensive content"


async def test_handle_flag_string_object(db, test_user, mock_valkey):
    """Flag with object as a single string (not list) should also work."""
    from app.activitypub.handlers.flag import handle_flag

    reporter = await make_remote_actor(db, username="rep3", domain="rep3.example")
    activity = {
        "type": "Flag",
        "id": "http://rep3.example/activities/flag3",
        "actor": reporter.ap_id,
        "object": test_user.actor.ap_id,
        "content": "",
    }
    await handle_flag(db, activity)

    result = await db.execute(
        select(Report).where(Report.reporter_actor_id == reporter.id)
    )
    report = result.scalar_one_or_none()
    assert report is not None
    assert report.target_actor_id == test_user.actor_id


async def test_handle_flag_missing_actor(db, mock_valkey):
    """Flag without actor field should be silently ignored."""
    from app.activitypub.handlers.flag import handle_flag

    activity = {
        "type": "Flag",
        "id": "http://example.com/flag4",
        "object": ["http://example.com/users/someone"],
    }
    await handle_flag(db, activity)

    result = await db.execute(select(Report))
    assert result.scalar_one_or_none() is None


async def test_handle_flag_unknown_target(db, mock_valkey):
    """Flag targeting an unknown actor should be silently ignored."""
    from app.activitypub.handlers.flag import handle_flag

    reporter = await make_remote_actor(db, username="rep5", domain="rep5.example")
    activity = {
        "type": "Flag",
        "id": "http://rep5.example/activities/flag5",
        "actor": reporter.ap_id,
        "object": ["http://nonexistent.example/users/unknown"],
        "content": "test",
    }
    await handle_flag(db, activity)

    result = await db.execute(
        select(Report).where(Report.reporter_actor_id == reporter.id)
    )
    assert result.scalar_one_or_none() is None


async def test_handle_flag_empty_object(db, mock_valkey):
    """Flag with empty object list should be silently ignored."""
    from app.activitypub.handlers.flag import handle_flag

    reporter = await make_remote_actor(db, username="rep6", domain="rep6.example")
    activity = {
        "type": "Flag",
        "id": "http://rep6.example/activities/flag6",
        "actor": reporter.ap_id,
        "object": [],
    }
    await handle_flag(db, activity)

    result = await db.execute(
        select(Report).where(Report.reporter_actor_id == reporter.id)
    )
    assert result.scalar_one_or_none() is None
