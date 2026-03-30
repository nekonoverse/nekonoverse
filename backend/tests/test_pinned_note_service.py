"""Tests for the pinned note service layer."""

import uuid

import pytest

from app.services.pinned_note_service import get_pinned_notes, pin_note, unpin_note
from tests.conftest import make_note


async def test_pin_note_success(db, test_user):
    note = await make_note(db, test_user.actor)
    await db.commit()

    pin = await pin_note(db, test_user, note.id)
    await db.commit()

    assert pin is not None
    assert pin.actor_id == test_user.actor.id
    assert pin.note_id == note.id
    assert pin.position == 0


async def test_pin_note_not_found(db, test_user):
    with pytest.raises(ValueError, match="Note not found"):
        await pin_note(db, test_user, uuid.uuid4())


async def test_pin_note_not_own_note(db, test_user, test_user_b):
    note = await make_note(db, test_user_b.actor)
    await db.commit()

    with pytest.raises(ValueError, match="Can only pin your own notes"):
        await pin_note(db, test_user, note.id)


async def test_pin_note_already_pinned(db, test_user):
    note = await make_note(db, test_user.actor)
    await db.commit()

    await pin_note(db, test_user, note.id)
    await db.commit()

    with pytest.raises(ValueError, match="Already pinned"):
        await pin_note(db, test_user, note.id)


async def test_pin_note_max_exceeded(db, test_user):
    notes = []
    for _ in range(5):
        n = await make_note(db, test_user.actor)
        notes.append(n)
    await db.commit()

    for n in notes:
        await pin_note(db, test_user, n.id)
        await db.commit()

    extra_note = await make_note(db, test_user.actor)
    await db.commit()

    with pytest.raises(ValueError, match="Maximum 5 pinned notes allowed"):
        await pin_note(db, test_user, extra_note.id)


async def test_unpin_note_success(db, test_user):
    note = await make_note(db, test_user.actor)
    await db.commit()

    await pin_note(db, test_user, note.id)
    await db.commit()

    await unpin_note(db, test_user, note.id)
    await db.commit()

    pins = await get_pinned_notes(db, test_user.actor.id)
    assert len(pins) == 0


async def test_unpin_note_not_pinned(db, test_user):
    note = await make_note(db, test_user.actor)
    await db.commit()

    with pytest.raises(ValueError, match="Not pinned"):
        await unpin_note(db, test_user, note.id)


async def test_get_pinned_notes_empty(db, test_user):
    pins = await get_pinned_notes(db, test_user.actor.id)
    assert pins == []


async def test_get_pinned_notes_ordered(db, test_user):
    notes = []
    for _ in range(3):
        n = await make_note(db, test_user.actor)
        notes.append(n)
    await db.commit()

    for n in notes:
        await pin_note(db, test_user, n.id)
        await db.commit()

    pins = await get_pinned_notes(db, test_user.actor.id)
    assert len(pins) == 3
    # positionの昇順でソートされていること
    assert pins[0].position <= pins[1].position <= pins[2].position
    # ピン留めした順序で返されること
    assert pins[0].note_id == notes[0].id
    assert pins[1].note_id == notes[1].id
    assert pins[2].note_id == notes[2].id
