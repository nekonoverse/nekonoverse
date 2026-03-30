"""Tests for report_service."""

import uuid

from app.services.report_service import (
    create_report,
    get_report_by_id,
    list_reports,
    reject_report,
    resolve_report,
)
from tests.conftest import make_note


async def test_create_report_basic(db, test_user, test_user_b):
    """Create a basic report with reporter and target actors."""
    report = await create_report(db, test_user.actor, test_user_b.actor)
    assert report.id is not None
    assert report.reporter_actor_id == test_user.actor.id
    assert report.target_actor_id == test_user_b.actor.id
    assert report.status == "open"
    assert report.target_note_id is None
    assert report.comment is None


async def test_create_report_with_note(db, test_user, test_user_b):
    """Create a report that references a specific note."""
    note = await make_note(db, test_user_b.actor, content="bad content")
    report = await create_report(
        db, test_user.actor, test_user_b.actor, target_note=note
    )
    assert report.target_note_id == note.id


async def test_create_report_with_comment(db, test_user, test_user_b):
    """Create a report with a comment describing the issue."""
    report = await create_report(
        db, test_user.actor, test_user_b.actor, comment="This user is spamming"
    )
    assert report.comment == "This user is spamming"


async def test_list_reports_empty(db):
    """Listing reports when none exist returns an empty list."""
    reports = await list_reports(db)
    assert reports == []


async def test_list_reports_all(db, test_user, test_user_b):
    """Listing reports returns all created reports."""
    await create_report(db, test_user.actor, test_user_b.actor, comment="report 1")
    await create_report(db, test_user_b.actor, test_user.actor, comment="report 2")
    reports = await list_reports(db)
    assert len(reports) == 2


async def test_list_reports_filter_by_status(db, test_user, test_user_b):
    """Filtering reports by status returns only matching reports."""
    report1 = await create_report(db, test_user.actor, test_user_b.actor, comment="to resolve")
    await create_report(db, test_user_b.actor, test_user.actor, comment="stays open")
    await resolve_report(db, report1, test_user)

    open_reports = await list_reports(db, status_filter="open")
    assert len(open_reports) == 1
    assert open_reports[0].comment == "stays open"

    resolved_reports = await list_reports(db, status_filter="resolved")
    assert len(resolved_reports) == 1
    assert resolved_reports[0].comment == "to resolve"


async def test_get_report_by_id(db, test_user, test_user_b):
    """Fetching a report by its ID returns the correct report."""
    report = await create_report(db, test_user.actor, test_user_b.actor, comment="find me")
    found = await get_report_by_id(db, report.id)
    assert found is not None
    assert found.id == report.id
    assert found.comment == "find me"


async def test_get_report_by_id_not_found(db):
    """Fetching a non-existent report returns None."""
    found = await get_report_by_id(db, uuid.uuid4())
    assert found is None


async def test_resolve_report(db, test_user, test_user_b):
    """Resolving a report sets status, moderator, and resolved_at."""
    report = await create_report(db, test_user.actor, test_user_b.actor)
    resolved = await resolve_report(db, report, test_user)
    assert resolved.status == "resolved"
    assert resolved.resolved_by_id == test_user.id
    assert resolved.resolved_at is not None


async def test_reject_report(db, test_user, test_user_b):
    """Rejecting a report sets status to 'rejected'."""
    report = await create_report(db, test_user.actor, test_user_b.actor)
    rejected = await reject_report(db, report, test_user)
    assert rejected.status == "rejected"
    assert rejected.resolved_by_id == test_user.id
    assert rejected.resolved_at is not None
