import math
from unittest.mock import AsyncMock, patch

import pytest

from backend import main
from backend.api.v1 import timecards
from backend.api.v1.timecards import _resolve_entry, _validate_timecard_entry
from backend.core.auth import SessionContext
from backend.services import timecard_entries


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
    response = client.post(
        "/api/auth/login", json={"username": "testuser", "password": "dummy-password"}
    )
    assert response.status_code == 200
    return client


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

    assert response.status_code == 200
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

    assert response.status_code == 200
    event = response.json()["items"][0]["timeRecordEvent"][0]
    assert event["eventStatus"] == "Approved"
