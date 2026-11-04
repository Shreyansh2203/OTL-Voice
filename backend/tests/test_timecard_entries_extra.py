import os
from unittest.mock import patch

import pytest

from backend.core.auth import SessionContext
from backend.services import timecard_entries
from backend.services.timecard_entries import (
    _entry_hours,
    _format_limit,
    _parse_date,
    _parse_time,
    _positive_number,
    _validate_times,
)

# --- _normalize_entry ---


def test_normalize_entry_aliases():
    """Cover lines 43-58: alias normalization."""
    entry = {
        "project_number": "P1",
        "project_name": "Alpha",
        "task_name": "Dev",
        "work_order_number": "WO-1",
        "person_number": "123",
        "employee_name": "Test User",
        "request_id": "req-1",
        "idempotency_key": "idem-1",
    }
    result = timecard_entries._normalize_entry(entry)
    assert result["projectNo"] == "P1"
    assert result["projectName"] == "Alpha"
    assert result["taskDetails"] == "Dev"
    assert result["workOrder"] == "WO-1"
    assert result["employeeNumber"] == "123"
    assert result["employeeName"] == "Test User"
    assert result["requestId"] == "req-1"
    assert result["idempotencyKey"] == "idem-1"


def test_normalize_entry_no_alias_when_target_exists():
    """Cover lines 55-57: alias not applied when target already set."""
    entry = {"project_number": "P1", "projectNo": "P2"}
    result = timecard_entries._normalize_entry(entry)
    assert result["projectNo"] == "P2"


# --- _extract_entries ---


def test_extract_entries_empty_message():
    """Cover lines 62-63: empty/None assistant message returns []."""
    assert timecard_entries._extract_entries("") == []
    assert timecard_entries._extract_entries(None) == []


def test_extract_entries_fenced_json_invalid():
    """Cover lines 65-69: fenced JSON with invalid JSON raises ValueError."""
    with pytest.raises(ValueError, match="malformed timecard JSON"):
        timecard_entries._extract_entries("```json\n{invalid}\n```")


def test_extract_entries_fenced_json_list():
    """Cover lines 70-71: fenced JSON list."""
    msg = '```json\n[{"projectNo": "P1", "hours": 8}]\n```'
    result = timecard_entries._extract_entries(msg)
    assert len(result) == 1
    assert result[0]["projectNo"] == "P1"


def test_extract_entries_fenced_json_dict_with_entries():
    """Cover lines 72-75: fenced JSON dict with entries key."""
    msg = '```json\n{"entries": [{"projectNo": "P1", "hours": 8}]}\n```'
    result = timecard_entries._extract_entries(msg)
    assert len(result) == 1


def test_extract_entries_plain_json_list():
    """Cover lines 76-79: plain JSON list without fences."""
    msg = '[{"projectNo": "P1", "hours": 8}]'
    result = timecard_entries._extract_entries(msg)
    assert len(result) == 1


def test_extract_entries_plain_json_dict_with_entries():
    """Cover lines 80-83: plain JSON dict with entries key."""
    msg = '{"entries": [{"projectNo": "P1", "hours": 8}]}'
    result = timecard_entries._extract_entries(msg)
    assert len(result) == 1


def test_extract_entries_invalid_json_returns_empty():
    """Cover lines 77, 84-86: invalid JSON falls back gracefully."""
    assert timecard_entries._extract_entries("not json at all") == []


# --- _strict_assignment ---


def test_strict_assignment_false_env_ignored():
    """Cover lines 100-109: STRICT_ASSIGNMENT=false is ignored."""
    from backend.services import timecard_entries as te

    te._STRICT_ASSIGNMENT_CACHE = None
    with patch.dict(os.environ, {"STRICT_ASSIGNMENT": "false"}, clear=False):
        assert te._strict_assignment() is True
    te._STRICT_ASSIGNMENT_CACHE = None


def test_strict_assignment_true_env():
    """Cover lines 100-109: STRICT_ASSIGNMENT=true."""
    from backend.services import timecard_entries as te

    te._STRICT_ASSIGNMENT_CACHE = None
    with patch.dict(os.environ, {"STRICT_ASSIGNMENT": "true"}, clear=False):
        assert te._strict_assignment() is True
    te._STRICT_ASSIGNMENT_CACHE = None


# --- _positive_number ---


def test_positive_number_none_and_empty():
    """Cover line 114: None and empty string return None."""
    assert _positive_number(None) is None
    assert _positive_number("") is None


def test_positive_number_bool():
    """Cover line 114: bool returns None."""
    assert _positive_number(True) is None
    assert _positive_number(False) is None


def test_positive_number_invalid():
    """Cover lines 117-119: invalid values return None."""
    assert _positive_number("abc") is None
    assert _positive_number("1.5.6") is None


def test_positive_number_non_finite():
    """Cover line 120: non-finite returns None."""
    from decimal import Decimal

    assert _positive_number(Decimal("Infinity")) is None
    assert _positive_number(Decimal("-Infinity")) is None


# --- _entry_hours ---


def test_entry_hours_none_and_zero():
    """Cover lines 124-128: None and <=0 hours errors."""
    num, err = _entry_hours({})
    assert num is None
    assert "required" in err

    num, err = _entry_hours({"hours": 0})
    assert num is None
    assert "greater than zero" in err

    num, err = _entry_hours({"hours": -5})
    assert num is None
    assert "greater than zero" in err


def test_entry_hours_not_quarter_hour():
    """Cover lines 129-131: non-quarter-hour hours error."""
    num, err = _entry_hours({"hours": 0.3})
    assert num is None
    assert "whole number, half hour, or quarter hour" in err


def test_entry_hours_exceeds_max():
    """Cover lines 132-138: hours exceeding max error."""
    num, err = _entry_hours({"hours": 100})
    assert num is None
    assert "cannot exceed" in err


def test_entry_hours_valid():
    """Cover lines 123-138: valid hours."""
    num, err = _entry_hours({"hours": 8})
    assert num == 8
    assert err is None


# --- _format_limit ---


def test_format_limit():
    """Cover lines 141-142: format_limit quantization."""
    from decimal import Decimal

    assert _format_limit(Decimal("24.00")) == "24"
    assert _format_limit(Decimal("24.50")) == "24.5"
    assert _format_limit(Decimal("8.25")) == "8.25"


# --- _parse_date ---


def test_parse_date_none_and_empty():
    """Cover lines 146-151: None and empty date errors."""
    assert _parse_date(None) is None
    with pytest.raises(ValueError, match="cannot be empty"):
        _parse_date("")


def test_parse_date_invalid_format():
    """Cover line 152: invalid format error."""
    with pytest.raises(ValueError, match="Invalid date format"):
        _parse_date("09/25/2026")


def test_parse_date_invalid_value():
    """Cover lines 154-157: invalid calendar date error."""
    with pytest.raises(ValueError, match="real calendar date"):
        _parse_date("2026-02-30")


def test_parse_date_non_string():
    """Cover line 148-149: non-string raises TypeError."""
    with pytest.raises(TypeError, match="must be a string"):
        _parse_date(123)


# --- _parse_time ---


def test_parse_time_none_and_empty():
    """Cover lines 160-166: None and empty time errors."""
    assert _parse_time("startTime", None) is None
    with pytest.raises(ValueError, match="cannot be empty"):
        _parse_time("startTime", "")


def test_parse_time_non_string():
    """Cover lines 163-164: non-string raises TypeError."""
    with pytest.raises(TypeError, match="must be a string"):
        _parse_time("startTime", 123)


def test_parse_time_invalid_format():
    """Cover lines 167-168: invalid format error."""
    with pytest.raises(ValueError, match="Invalid startTime format"):
        _parse_time("startTime", "9:00")


def test_parse_time_invalid_value():
    """Cover lines 169-174: invalid time value error."""
    with pytest.raises(ValueError, match="real 24-hour time"):
        _parse_time("startTime", "25:00")


# --- _validate_times ---


def test_validate_times_stop_without_start():
    """Cover lines 187-188: stopTime without startTime error."""
    from decimal import Decimal

    err = _validate_times({"startTime": None, "stopTime": "17:00"}, Decimal("8"))
    assert "startTime" in err


def test_validate_times_stop_before_start():
    """Cover lines 193-194: stop before start error."""
    from decimal import Decimal

    err = _validate_times({"startTime": "17:00", "stopTime": "09:00"}, Decimal("8"))
    assert "earlier than stopTime" in err


def test_validate_times_mismatch_hours():
    """Cover lines 195-198: stopTime doesn't match hours error."""
    from decimal import Decimal

    err = _validate_times({"startTime": "09:00", "stopTime": "12:00"}, Decimal("8"))
    assert "exactly match" in err


def test_validate_times_valid():
    """Cover lines 181-198: valid times."""
    from decimal import Decimal

    assert (
        _validate_times({"startTime": "09:00", "stopTime": "17:00"}, Decimal("8"))
        is None
    )


# --- _configured_allowlist ---


def test_configured_allowlist_env_var():
    """Cover lines 201-211: env var overrides defaults."""
    with patch.dict(
        os.environ, {"OTL_ALLOWED_PAYROLL_TIME_TYPES": "Regular,Overtime"}, clear=False
    ):
        result = timecard_entries._configured_allowlist(
            ("OTL_ALLOWED_PAYROLL_TIME_TYPES",), ("Regular",)
        )
        assert result == frozenset({"Regular", "Overtime"})


def test_configured_allowlist_empty_values():
    """Cover line 211: empty values filtered out."""
    with patch.dict(
        os.environ, {"OTL_ALLOWED_PAYROLL_TIME_TYPES": "Regular,,Overtime"}, clear=False
    ):
        result = timecard_entries._configured_allowlist(
            ("OTL_ALLOWED_PAYROLL_TIME_TYPES",), ("Regular",)
        )
        assert result == frozenset({"Regular", "Overtime"})


# --- _validate_allowlisted_value ---


def test_validate_allowlisted_value_not_string():
    """Cover lines 220-224: non-string value error."""
    err = timecard_entries._validate_allowlisted_value(
        {"payrollTimeType": 123}, "payrollTimeType", ("X",), ("Y",)
    )
    assert "non-empty string" in err


# --- _entry_idempotency_error ---


def test_entry_idempotency_error():
    """Cover lines 256-263: idempotency key error."""
    err = timecard_entries._entry_idempotency_error(
        {"employeeNumber": "123", "hours": 8, "requestId": "A", "idempotencyKey": "B"}
    )
    assert err is not None
    assert "Conflicting" in err


# --- _assigned_project ---


def test_assigned_project_none_assignments():
    """Cover lines 273-274: None assignments returns None,None."""
    result, err = timecard_entries._assigned_project({}, None)
    assert result is None
    assert err is None


def test_assigned_project_project_not_found():
    """Cover lines 295-296: project not in assigned projects error."""
    assignments = [
        {
            "workOrder": "WO-1",
            "projects": [{"projectNo": "P1", "projectName": "Alpha"}],
        }
    ]
    result, err = timecard_entries._assigned_project({"projectNo": "P2"}, assignments)
    assert result is None
    assert "not in your assigned projects" in err


def test_assigned_project_ambiguous():
    """Cover lines 297-307: ambiguous project reference error."""
    assignments = [
        {
            "workOrder": "WO-1",
            "projects": [{"projectNo": "P1", "projectName": "Alpha"}],
        },
        {
            "workOrder": "WO-2",
            "projects": [{"projectNo": "P1", "projectName": "Alpha"}],
        },
    ]
    result, err = timecard_entries._assigned_project({"projectNo": "P1"}, assignments)
    assert result is None
    assert "ambiguous" in err


def test_assigned_project_name_mismatch():
    """Cover lines 309-310: project name mismatch error."""
    assignments = [
        {
            "workOrder": "WO-1",
            "projects": [{"projectNo": "P1", "projectName": "Alpha"}],
        }
    ]
    result, err = timecard_entries._assigned_project(
        {"projectNo": "P1", "projectName": "Beta"}, assignments
    )
    assert result is None
    assert "name does not match" in err


def test_assigned_project_work_order_mismatch():
    """Cover lines 311-314: work order mismatch error."""
    assignments = [
        {
            "workOrder": "WO-1",
            "projects": [{"projectNo": "P1", "projectName": "Alpha"}],
        }
    ]
    result, err = timecard_entries._assigned_project(
        {"projectNo": "P1", "workOrder": "WO-2"}, assignments
    )
    assert result is None
    assert "Work order does not match" in err


# --- _validate_timecard_entry ---


def test_validate_timecard_entry_no_project():
    """Cover lines 343-349: no project number/name error."""
    valid, err = timecard_entries._validate_timecard_entry(
        {"hours": 8, "taskDetails": "Dev"}, None
    )
    assert valid is False
    assert "Project number or project name is required" in err


def test_validate_timecard_entry_no_task_details():
    """Cover lines 350-351: no task details error."""
    valid, err = timecard_entries._validate_timecard_entry(
        {"hours": 8, "projectNo": "P1"}, None
    )
    assert valid is False
    assert "Task details are required" in err


def test_validate_timecard_entry_task_not_assigned():
    """Cover lines 358-368: task not in assigned tasks error."""
    assignments = [
        {
            "workOrder": "WO-1",
            "projects": [
                {
                    "projectNo": "P1",
                    "projectName": "Alpha",
                    "tasks": [{"taskId": "T1", "taskDetails": "Dev"}],
                }
            ],
        }
    ]
    valid, err = timecard_entries._validate_timecard_entry(
        {"hours": 8, "projectNo": "P1", "taskId": "T99", "taskDetails": "Dev"},
        assignments,
    )
    assert valid is False
    assert "not assigned" in err


# --- _validate_timecard_entries ---


def test_validate_timecard_entries_daily_limit_undated():
    """Cover lines 389-394: undated daily limit error."""
    entries = [
        {"hours": 24, "projectNo": "P1", "taskDetails": "Dev"},
        {"hours": 1, "projectNo": "P1", "taskDetails": "Dev"},
    ]
    valid, err = timecard_entries._validate_timecard_entries(entries, None)
    assert valid is False
    assert "daily limit" in err


def test_validate_timecard_entries_daily_limit_dated():
    """Cover lines 395-398: dated daily limit error."""
    entries = [
        {"hours": 24, "projectNo": "P1", "taskDetails": "Dev", "date": "2026-01-01"},
        {"hours": 1, "projectNo": "P1", "taskDetails": "Dev", "date": "2026-01-01"},
    ]
    valid, err = timecard_entries._validate_timecard_entries(entries, None)
    assert valid is False
    assert "daily limit" in err


# --- _resolve_entry ---


def test_resolve_entry_no_project():
    """Cover lines 411-421: resolve entry without project."""
    ctx = SessionContext(employee_id="123", username="user", full_name="Test User")
    result = timecard_entries._resolve_entry(
        {"hours": 8, "projectNo": "P1", "taskDetails": "Dev"}, ctx, None
    )
    assert result["employeeNumber"] == "123"
    assert result["employeeName"] == "Test User"
    assert result["projectNo"] == "P1"


def test_resolve_entry_task_id_from_details():
    """Cover lines 422-431: resolve taskId from taskDetails."""
    ctx = SessionContext(employee_id="123", username="user", full_name="Test User")
    assignments = [
        {
            "workOrder": "WO-1",
            "projects": [
                {
                    "projectNo": "P1",
                    "projectName": "Alpha",
                    "tasks": [{"taskId": "T1", "taskDetails": "Development"}],
                }
            ],
        }
    ]
    result = timecard_entries._resolve_entry(
        {"hours": 8, "projectNo": "P1", "taskDetails": "Development"}, ctx, assignments
    )
    assert result["taskId"] == "T1"


# --- _options_hint ---


def test_options_hint_no_projects():
    """Cover lines 442-443: no projects hint."""
    hint = timecard_entries._options_hint([])
    assert "no project assignments" in hint


def test_options_hint_truncation():
    """Cover lines 444-452: hint truncation."""
    assignments = [
        {
            "workOrder": f"WO-{i}",
            "projects": [{"projectNo": f"P{i}", "projectName": f"Alpha{i}"}],
        }
        for i in range(20)
    ]
    hint = timecard_entries._options_hint(assignments)
    assert "... and 10 more" in hint
    assert len(hint) <= 500
