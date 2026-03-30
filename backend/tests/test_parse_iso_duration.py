"""Tests for _parse_iso_duration in note_service.py。"""

from app.services.note_service import _parse_iso_duration


def test_parse_seconds_only():
    assert _parse_iso_duration("PT30.5S") == 30.5


def test_parse_minutes_and_seconds():
    assert _parse_iso_duration("PT1M30S") == 90.0


def test_parse_hours_minutes_seconds():
    assert _parse_iso_duration("PT1H2M3S") == 3723.0


def test_parse_minutes_only():
    assert _parse_iso_duration("PT5M") == 300.0


def test_parse_hours_only():
    assert _parse_iso_duration("PT2H") == 7200.0


def test_parse_invalid_returns_none():
    assert _parse_iso_duration("invalid") is None


def test_parse_empty_returns_none():
    assert _parse_iso_duration("") is None


def test_parse_zero():
    assert _parse_iso_duration("PT0S") == 0.0


def test_parse_malformed_seconds_multiple_dots():
    """float("1.2.3") は ValueError — None を返すこと。"""
    assert _parse_iso_duration("PT1.2.3S") is None


def test_parse_dot_only_seconds():
    """float(".") は ValueError — None を返すこと。"""
    assert _parse_iso_duration("PT.S") is None
