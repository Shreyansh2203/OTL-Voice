import json
import math
import sqlite3
from unittest.mock import AsyncMock, patch

import pytest

from backend import main
from backend.api.v1 import timecards
from backend.api.v1.timecards import _resolve_entry, _validate_timecard_entry
from backend.core import auth
from backend.core.auth import SessionContext
from backend.schemas.timecards import TimecardBody
from backend.services import fusion_catalogue, timecard_entries


@pytest.fixture(autouse=True)
def close_mock_client():
    with patch("backend.main.otl_client.close_shared_client", new_callable=AsyncMock):
        yield


@pytest.fixture
def auth_client(client, mock_otl_client):
    mock_otl_client.aget_worker.return_value = {
        "personNumber": "testuser",
        "fullName": "Test User",
    }
    main.app.dependency_overrides[auth.current_session] = lambda: SessionContext(
        employee_id="testuser",
        username="testuser",
        full_name="Test User",
    )
    yield client
    main.app.dependency_overrides.pop(auth.current_session, None)


def _entry(**overrides):
    value = {
        "projectNo": "P1",
        "projectName": "Alpha",
        "taskDetails": "Development",
        "hours": 8,
    }
    value.update(overrides)
    return value


def test_timecard_helper_facade_exports_service_helpers():
    assert timecards._FENCED_JSON is timecard_entries._FENCED_JSON
    assert timecards._normalize_entry is timecard_entries._normalize_entry
    assert timecards._extract_entries is timecard_entries._extract_entries
    assert timecards._strict_assignment is timecard_entries._strict_assignment
    assert (
        timecards._STRICT_ASSIGNMENT_CACHE == timecard_entries._STRICT_ASSIGNMENT_CACHE
    )
    assert timecards._validate_timecard_entry is (
        timecard_entries._validate_timecard_entry
    )
    assert timecards._resolve_entry is timecard_entries._resolve_entry
    assert timecards._options_hint is timecard_entries._options_hint
    assert timecards.MAX_TIMECARD_ENTRIES == timecard_entries.MAX_TIMECARD_ENTRIES


def test_main_preserves_timecard_helper_imports():
    assert main._extract_entries is timecards._extract_entries
    assert main._options_hint is timecards._options_hint
    assert main._strict_assignment is timecards._strict_assignment


def test_validate_rejects_bool_and_non_finite_hours():
    for hours in (True, math.nan, math.inf, -math.inf):
        valid, error = _validate_timecard_entry(_entry(hours=hours))
        assert valid is False
        assert "finite" in (error or "").lower()


def test_validate_task_id_belongs_to_selected_project():
    assignments = [
        {
            "workOrder": "WO-1",
            "projects": [
                {
                    "projectNo": "P1",
                    "projectName": "Alpha",
                    "tasks": [{"taskId": "T1", "taskDetails": "Development"}],
                },
                {
                    "projectNo": "P2",
                    "projectName": "Beta",
                    "tasks": [{"taskId": "T2", "taskDetails": "Development"}],
                },
            ],
        }
    ]

    valid, error = _validate_timecard_entry(_entry(taskId="T2"), assignments)

    assert valid is False
    assert "P1" in (error or "")


def test_validate_accepts_task_id_for_selected_project():
    assignments = [
        {
            "projects": [
                {
                    "projectNo": "P1",
                    "projectName": "Alpha",
                    "tasks": [{"taskId": "T1", "taskDetails": "Development"}],
                }
            ]
        }
    ]

    assert _validate_timecard_entry(_entry(taskId="T1"), assignments) == (True, None)


def test_resolve_preserves_project_id_without_assignments():
    ctx = SessionContext(employee_id="1", username="user", full_name="Test User")
    resolved = _resolve_entry(_entry(projectId="SUPPLIED"), ctx, [])

    assert resolved["projectId"] == "SUPPLIED"
    assert resolved["projectNo"] == "P1"


def test_submit_waits_for_catalogue_cold_start(auth_client, mock_fusion_catalogue):
    mock_fusion_catalogue.alist_assignments_for_worker.return_value = None

    with patch("backend.services.timecard_entries._STRICT_ASSIGNMENT_CACHE", True):
        response = auth_client.post("/api/otl/timecard", json={"entries": [_entry()]})

    assert response.status_code == 503
    assert "not loaded" in response.json()["detail"].lower()


def test_non_strict_submit_preserves_supplied_project_id(auth_client, mock_otl_client):
    entry = _entry(projectId="SUPPLIED")
    entry.pop("projectNo")
    entry.pop("projectName")
    with (
        patch.dict("os.environ", {"STRICT_ASSIGNMENT": "false"}),
        patch("backend.services.timecard_entries._STRICT_ASSIGNMENT_CACHE", False),
    ):
        response = auth_client.post(
            "/api/otl/timecard",
            json={"entries": [entry]},
        )

    assert response.status_code == 200, response.text
    submitted = mock_otl_client.acreate_many.await_args.args[1]
    assert submitted[0]["projectId"] == "SUPPLIED"


def test_submit_rejects_task_from_another_project(auth_client, mock_fusion_catalogue):
    mock_fusion_catalogue.alist_assignments_for_worker.return_value = [
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

    with patch("backend.services.timecard_entries._STRICT_ASSIGNMENT_CACHE", True):
        response = auth_client.post(
            "/api/otl/timecard", json={"entries": [_entry(taskId="T2")]}
        )

    assert response.status_code == 400
    assert "not assigned" in response.json()["detail"].lower()


def test_timecard_status_is_propagated(auth_client, mock_otl_client):
    mock_otl_client.alist_timecard_entries.return_value = {
        "items": [
            {"timeRecordEvent": [{"timeStatuses": [{"displayValue": "Approved"}]}]}
        ]
    }

    response = auth_client.get("/api/otl/timecards")

    assert response.status_code == 200, response.text
    event = response.json()["items"][0]["timeRecordEvent"][0]
    assert event["eventStatus"] == "Approved"


def test_quarter_half_and_whole_hour_policy():
    for hours in (0.25, 0.5, 1, 8, 24):
        assert _validate_timecard_entry(_entry(hours=hours)) == (True, None)

    valid, error = _validate_timecard_entry(_entry(hours=0.1))

    assert valid is False
    assert "whole number, half hour, or quarter hour" in (error or "")


def test_per_entry_and_daily_hour_caps():
    valid, error = _validate_timecard_entry(_entry(hours=24.25))
    assert valid is False
    assert "one entry" in (error or "")

    entries = [
        _entry(hours=24, date="2026-09-25"),
        _entry(hours=0.25, date="2026-09-25"),
    ]
    valid, error = timecard_entries._validate_timecard_entries(entries)

    assert valid is False
    assert "daily limit" in (error or "")


def test_explicit_times_must_be_ordered_and_match_hours():
    for start, stop, hours, expected in (
        ("09:00", "09:00", 8, "earlier"),
        ("17:00", "09:00", 8, "earlier"),
        ("09:00", "12:00", 8, "exactly match"),
    ):
        valid, error = _validate_timecard_entry(
            _entry(startTime=start, stopTime=stop, hours=hours)
        )
        assert valid is False
        assert expected in (error or "")

    assert _validate_timecard_entry(
        _entry(startTime="09:00", stopTime="09:15", hours=0.25)
    ) == (True, None)
    valid, error = _validate_timecard_entry(_entry(stopTime="17:00"))
    assert valid is False
    assert "requires an explicit startTime" in (error or "")


def test_date_and_time_syntax_is_strict():
    for field, value, expected in (
        ("date", "09/25/2026", "date format"),
        ("date", "2026-02-30", "calendar date"),
        ("startTime", "9:00", "starttime format"),
        ("startTime", "09:60", "starttime value"),
        ("stopTime", "17:00:00", "stoptime format"),
    ):
        valid, error = _validate_timecard_entry(_entry(**{field: value}))
        assert valid is False
        assert expected in (error or "").lower()


def test_payroll_and_expenditure_allowlists():
    assert _validate_timecard_entry(
        _entry(payrollTimeType="Regular", expenditureType="Professional Services")
    ) == (True, None)

    valid, error = _validate_timecard_entry(_entry(payrollTimeType="Not A Type"))
    assert valid is False
    assert "configured allowlist" in (error or "")

    with patch.dict(
        "os.environ",
        {"OTL_ALLOWED_EXPENDITURE_TYPES": "Approved Expense"},
    ):
        assert _validate_timecard_entry(_entry(expenditureType="Approved Expense")) == (
            True,
            None,
        )
        valid, error = _validate_timecard_entry(
            _entry(expenditureType="Professional Services")
        )
        assert valid is False
        assert "configured allowlist" in (error or "")


def test_catalogue_never_falls_back_to_full_name():
    connection = sqlite3.connect(":memory:")
    connection.execute(
        "CREATE TABLE person_index (name TEXT PRIMARY KEY, projects JSON)"
    )
    connection.execute(
        "INSERT INTO person_index (name, projects) VALUES (?, ?)",
        ("12345", json.dumps([{"project_id": "private-project"}])),
    )
    connection.commit()

    with patch("backend.services.fusion_catalogue._get_db", return_value=connection):
        assert fusion_catalogue._find_person_projects("", "Alice") == []
        assert fusion_catalogue._find_person_projects("alice", "Other") == []
        assert fusion_catalogue._find_person_projects("missing-id", "Alice") == []
        assert fusion_catalogue._find_person_projects("12345", "Other") == [
            {"project_id": "private-project"}
        ]

    connection.close()


def test_catalogue_does_not_index_employee_names_or_ambiguous_ids():
    index = fusion_catalogue._build_index(
        [
            {
                "project_id": "P1",
                "project_number": "1001",
                "project_name": "Alpha",
                "team_members": [
                    {"PersonId": "person-1", "PersonName": "Alice"},
                    {"PersonId": "person-2", "PersonName": "Bob"},
                ],
            },
            {
                "project_id": "P2",
                "project_number": "1002",
                "project_name": "Beta",
                "team_members": [
                    {"PersonId": "person-2", "PersonName": "Robert"},
                ],
            },
        ]
    )

    assert "alice" not in index
    assert "bob" not in index
    assert "person-1" in index
    assert "person-2" not in index


def test_timecard_body_accepts_idempotency_fields():
    body = TimecardBody(
        entries=[{"requestId": "request-123", "hours": 1}],
        requestId="request-123",
    )

    assert body.entries is not None
    assert body.entries[0]["requestId"] == "request-123"
    assert body.requestId == "request-123"


def test_submit_rejects_invalid_idempotency_header_without_writes(
    auth_client, mock_otl_client
):
    with patch("backend.services.timecard_entries._STRICT_ASSIGNMENT_CACHE", False):
        response = auth_client.post(
            "/api/otl/timecard",
            json={"entries": [_entry()]},
            headers={"Idempotency-Key": "invalid key"},
        )

    assert response.status_code == 400
    assert "requestId" in response.json()["detail"]
    mock_otl_client.acreate_many.assert_not_awaited()


def test_submit_rejects_duplicate_entry_request_ids(auth_client, mock_otl_client):
    with patch("backend.services.timecard_entries._STRICT_ASSIGNMENT_CACHE", False):
        response = auth_client.post(
            "/api/otl/timecard",
            json={
                "entries": [
                    _entry(requestId="request-duplicate"),
                    _entry(requestId="request-duplicate"),
                ]
            },
        )

    assert response.status_code == 400
    assert "unique" in response.json()["detail"].lower()
    mock_otl_client.acreate_many.assert_not_awaited()


def test_submit_hides_internal_submission_error(auth_client, mock_otl_client):
    mock_otl_client.acreate_many.side_effect = RuntimeError(
        "ORA-00933 password=supersecret"
    )

    with patch("backend.services.timecard_entries._STRICT_ASSIGNMENT_CACHE", False):
        response = auth_client.post(
            "/api/otl/timecard",
            json={"entries": [_entry(requestId="request-safe-error")]},
        )

    assert response.status_code == 502
    detail = response.json()["detail"]
    assert "supersecret" not in detail
    assert "ORA-00933" not in detail
    assert "reference" in detail.lower()


def test_submit_sanitizes_per_row_error(auth_client, mock_otl_client):
    mock_otl_client.acreate_many.return_value = [
        {
            "index": 0,
            "ok": False,
            "status": 500,
            "error": "Traceback with password=supersecret",
            "detail": {"internal": True},
        }
    ]

    with patch("backend.services.timecard_entries._STRICT_ASSIGNMENT_CACHE", False):
        response = auth_client.post(
            "/api/otl/timecard",
            json={"entries": [_entry(requestId="request-row-safe")]},
        )

    assert response.status_code == 200, response.text
    result = response.json()["results"][0]
    assert result["error"] == "Oracle Cloud is temporarily unavailable."
    assert "supersecret" not in str(result).lower()
    assert "detail" not in result
