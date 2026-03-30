"""Tests for poll API endpoints."""

import uuid
from unittest.mock import AsyncMock, patch

SAMPLE_POLL_DATA = {
    "id": str(uuid.uuid4()),
    "expires_at": None,
    "expired": False,
    "multiple": False,
    "votes_count": 3,
    "voters_count": 3,
    "options": [
        {"title": "Option A", "votes_count": 2},
        {"title": "Option B", "votes_count": 1},
    ],
    "voted": False,
    "own_votes": [],
}


@patch(
    "app.services.poll_service.get_poll_data",
    new_callable=AsyncMock,
    return_value=SAMPLE_POLL_DATA,
)
async def test_get_poll(mock_get_poll, app_client, db):
    """GET /api/v1/polls/{note_id} returns poll data."""
    note_id = uuid.uuid4()
    resp = await app_client.get(f"/api/v1/polls/{note_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["votes_count"] == 3
    assert len(data["options"]) == 2
    assert data["options"][0]["title"] == "Option A"


@patch(
    "app.services.poll_service.get_poll_data",
    new_callable=AsyncMock,
    return_value=None,
)
async def test_get_poll_not_found(mock_get_poll, app_client, db):
    """GET /api/v1/polls/{note_id} returns 404 when poll does not exist."""
    note_id = uuid.uuid4()
    resp = await app_client.get(f"/api/v1/polls/{note_id}")
    assert resp.status_code == 404


@patch("app.services.poll_service.get_poll_data", new_callable=AsyncMock)
@patch("app.services.poll_service.vote_on_poll", new_callable=AsyncMock)
async def test_vote_on_poll(mock_vote, mock_get_poll, authed_client, test_user, db):
    """POST /api/v1/polls/{note_id}/votes records a vote and returns poll data."""
    note_id = uuid.uuid4()
    voted_data = {**SAMPLE_POLL_DATA, "voted": True, "own_votes": [0]}
    mock_get_poll.return_value = voted_data

    resp = await authed_client.post(
        f"/api/v1/polls/{note_id}/votes",
        json={"choices": [0]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["voted"] is True
    assert 0 in data["own_votes"]
    mock_vote.assert_called_once()


@patch("app.services.poll_service.get_poll_data", new_callable=AsyncMock)
@patch(
    "app.services.poll_service.vote_on_poll",
    new_callable=AsyncMock,
    side_effect=ValueError("Already voted"),
)
async def test_vote_on_poll_invalid(
    mock_vote, mock_get_poll, authed_client, test_user, db
):
    """POST /api/v1/polls/{note_id}/votes returns 422 when vote is invalid."""
    note_id = uuid.uuid4()
    resp = await authed_client.post(
        f"/api/v1/polls/{note_id}/votes",
        json={"choices": [0]},
    )
    assert resp.status_code == 422
    assert "Already voted" in resp.json()["detail"]


async def test_vote_unauthenticated(app_client, db):
    """POST /api/v1/polls/{note_id}/votes rejects unauthenticated requests."""
    note_id = uuid.uuid4()
    resp = await app_client.post(
        f"/api/v1/polls/{note_id}/votes",
        json={"choices": [0]},
    )
    assert resp.status_code in (401, 403)
