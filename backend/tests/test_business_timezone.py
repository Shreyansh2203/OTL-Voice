"""The business timezone must be honoured, not silently replaced."""

from __future__ import annotations

import logging
import sys
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from backend.services.otl_client import _business_timezone, map_entry_to_otl

ENTRY = {
    "employeeNumber": "10021",
    "date": "2026-03-01",
    "hours": 2,
    "startTime": "09:00",
    "stopTime": "11:00",
}


def _event(entry: dict[str, object]) -> Any:
    return map_entry_to_otl(dict(entry))["timeRecordEvent"][0]


def test_windows_development_ships_a_timezone_database() -> None:
    # A bare Windows install has no system zoneinfo, so the tzdata dev
    # dependency is what makes an IANA APP_TIMEZONE resolvable there.
    assert ZoneInfo("Asia/Kolkata") is not None
    if sys.platform == "win32":
        import tzdata  # noqa: F401


@pytest.mark.parametrize(
    ("name", "expected_offset"),
    [
        ("Asia/Kolkata", "+0530"),
        ("America/New_York", "-0400"),
        ("Europe/Berlin", "+0200"),
    ],
)
def test_configured_business_timezone_is_used(
    name: str, expected_offset: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_TIMEZONE", name)
    zone = _business_timezone()
    assert zone is not None
    summer = datetime(2026, 7, 1, 12, 0, tzinfo=UTC).astimezone(zone)
    assert summer.strftime("%z") == expected_offset
    # The configured zone must be what the caller gets back, not a copy of
    # the host zone that merely happens to share an offset.
    assert str(zone) == name


def test_timecard_offsets_follow_the_configured_business_timezone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_TIMEZONE", "Asia/Kolkata")
    event = _event(ENTRY)
    assert event["startTime"] == "2026-03-01T09:00:00.000+05:30"
    assert event["stopTime"] == "2026-03-01T11:00:00.000+05:30"


def test_half_hour_offset_zone_is_not_rounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_TIMEZONE", "Asia/Kolkata")
    event = _event(ENTRY)
    offset = str(event["startTime"])[-6:]
    assert offset == "+05:30"
    assert offset[3] == ":"


def test_unset_business_timezone_still_works(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APP_TIMEZONE", raising=False)
    event = _event(ENTRY)
    start = str(event["startTime"])
    assert start.startswith("2026-03-01T09:00:00.000")
    assert datetime.fromisoformat(start).utcoffset() is not None


def test_unknown_business_timezone_warns_and_falls_back(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("APP_TIMEZONE", "Mars/Olympus_Mons")
    with caplog.at_level(logging.WARNING, logger="backend.services.otl_client"):
        zone = _business_timezone()
    assert zone is not None
    assert "Unknown APP_TIMEZONE" in caplog.text
    assert "Mars/Olympus_Mons" in caplog.text
    event = _event(ENTRY)
    assert str(event["startTime"]).startswith("2026-03-01T09:00:00.000")


def test_blank_business_timezone_is_not_reported_as_unknown(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("APP_TIMEZONE", "   ")
    with caplog.at_level(logging.WARNING, logger="backend.services.otl_client"):
        zone = _business_timezone()
    assert zone is not None
    assert "Unknown APP_TIMEZONE" not in caplog.text
