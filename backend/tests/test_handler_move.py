"""Tests for Move activity handler."""

from unittest.mock import AsyncMock, patch

from tests.conftest import make_remote_actor


async def test_handle_move_calls_service(db, mock_valkey):
    """Move activity should resolve actors and call handle_incoming_move."""
    from app.activitypub.handlers.move import handle_move

    source = await make_remote_actor(db, username="old_acct", domain="old.example")
    target = await make_remote_actor(db, username="new_acct", domain="new.example")
    target.also_known_as = [source.ap_id]
    await db.commit()

    activity = {
        "type": "Move",
        "actor": source.ap_id,
        "target": target.ap_id,
    }

    with patch("app.services.move_service.handle_incoming_move", new_callable=AsyncMock) as mock_move:
        await handle_move(db, activity)
        mock_move.assert_called_once()
        call_args = mock_move.call_args
        assert call_args[0][1].ap_id == source.ap_id
        assert call_args[0][2] == target.ap_id


async def test_handle_move_uses_object_fallback(db, mock_valkey):
    """Move should use 'object' field when 'target' is missing."""
    from app.activitypub.handlers.move import handle_move

    source = await make_remote_actor(db, username="old2", domain="old2.example")

    activity = {
        "type": "Move",
        "actor": source.ap_id,
        "object": "http://new2.example/users/new2",
    }

    with patch("app.services.move_service.handle_incoming_move", new_callable=AsyncMock) as mock_move:
        await handle_move(db, activity)
        mock_move.assert_called_once()
        assert mock_move.call_args[0][2] == "http://new2.example/users/new2"


async def test_handle_move_missing_actor(db, mock_valkey):
    """Move without actor field should be silently ignored."""
    from app.activitypub.handlers.move import handle_move

    activity = {
        "type": "Move",
        "target": "http://example.com/users/someone",
    }

    with patch("app.services.move_service.handle_incoming_move", new_callable=AsyncMock) as mock_move:
        await handle_move(db, activity)
        mock_move.assert_not_called()


async def test_handle_move_missing_target(db, mock_valkey):
    """Move without target or object field should be silently ignored."""
    from app.activitypub.handlers.move import handle_move

    source = await make_remote_actor(db, username="old3", domain="old3.example")
    activity = {
        "type": "Move",
        "actor": source.ap_id,
    }

    with patch("app.services.move_service.handle_incoming_move", new_callable=AsyncMock) as mock_move:
        await handle_move(db, activity)
        mock_move.assert_not_called()


async def test_handle_move_unknown_source(db, mock_valkey):
    """Move with unresolvable source actor should be silently ignored."""
    from app.activitypub.handlers.move import handle_move

    activity = {
        "type": "Move",
        "actor": "http://nonexistent.example/users/ghost",
        "target": "http://new.example/users/new",
    }

    with patch("app.activitypub.handlers.move.fetch_remote_actor", new_callable=AsyncMock, return_value=None):
        with patch("app.services.move_service.handle_incoming_move", new_callable=AsyncMock) as mock_move:
            await handle_move(db, activity)
            mock_move.assert_not_called()
