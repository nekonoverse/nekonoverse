"""Tests for reaction streaming events via Valkey pub/sub."""

import json

import pytest

from tests.conftest import make_note, make_remote_actor


async def test_add_reaction_publishes_event(db, test_user, mock_valkey):
    from app.services.reaction_service import add_reaction

    note = await make_note(db, test_user.actor, visibility="public")
    await add_reaction(db, test_user, note, "\U0001f600")

    # Should have published to timeline:public for a public note
    calls = mock_valkey.publish.call_args_list
    channels = [c.args[0] for c in calls]
    assert "timeline:public" in channels

    # Verify event format
    for call in calls:
        event = json.loads(call.args[1])
        assert event["event"] == "status.reaction"
        assert event["payload"]["id"] == str(note.id)


async def test_remove_reaction_publishes_event(db, test_user, mock_valkey):
    from app.services.reaction_service import add_reaction, remove_reaction

    note = await make_note(db, test_user.actor, visibility="public")
    await add_reaction(db, test_user, note, "\U0001f600")
    mock_valkey.publish.reset_mock()

    await remove_reaction(db, test_user, note, "\U0001f600")

    calls = mock_valkey.publish.call_args_list
    channels = [c.args[0] for c in calls]
    assert "timeline:public" in channels

    for call in calls:
        event = json.loads(call.args[1])
        assert event["event"] == "status.reaction"


async def test_reaction_event_respects_visibility(db, test_user, mock_valkey):
    from app.services.reaction_service import add_reaction

    note = await make_note(db, test_user.actor, visibility="followers")
    await add_reaction(db, test_user, note, "\U0001f600")

    calls = mock_valkey.publish.call_args_list
    channels = [c.args[0] for c in calls]
    # Should NOT publish to timeline:public for followers-only note
    assert "timeline:public" not in channels
    # Should publish to author's home timeline
    assert f"timeline:home:{note.actor_id}" in channels


async def test_reaction_publishes_to_author_timeline(db, test_user, mock_valkey):
    from app.services.reaction_service import add_reaction

    note = await make_note(db, test_user.actor, visibility="public")
    await add_reaction(db, test_user, note, "\U0001f600")

    calls = mock_valkey.publish.call_args_list
    channels = [c.args[0] for c in calls]
    assert f"timeline:home:{note.actor_id}" in channels
