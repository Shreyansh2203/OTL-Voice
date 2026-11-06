import json
from unittest.mock import patch

import pytest

from backend import main
from backend.core import auth
from backend.core.auth import SessionContext


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


# --- submit_timecard: invalid assistant message JSON ---


def test_submit_invalid_assistant_message_json(auth_client, mock_fusion_catalogue):
    """Cover timecards.py:48-49 - ValueError from _extract_entries."""
    mock_fusion_catalogue.alist_assignments_for_worker.return_value = [
        {
            "workOrder": "WO-1",
            "projects": [{"projectNo": "P1", "projectName": "Alpha", "tasks": []}],
        }
    ]
    # Use assistantMessage that fails JSON parsing inside _extract_entries
    response = auth_client.post(
        "/api/otl/timecard",
        json={"assistantMessage": "```json\n{invalid}\n```"},
    )
    assert response.status_code == 422
    assert "valid timecard JSON" in response.json()["detail"]


# --- submit_timecard: too many entries ---


def test_submit_too_many_entries(auth_client, mock_fusion_catalogue):
    """Cover timecards.py:54 - entries exceed MAX_TIMECARD_ENTRIES."""
    mock_fusion_catalogue.alist_assignments_for_worker.return_value = [
        {
            "workOrder": "WO-1",
            "projects": [{"projectNo": "P1", "projectName": "Alpha", "tasks": []}],
        }
    ]
    # Use assistantMessage with too many entries to bypass Pydantic list validation
    entries_json = json.dumps([_entry() for _ in range(101)])
    response = auth_client.post(
        "/api/otl/timecard",
        json={"assistantMessage": f"```json\n{entries_json}\n```"},
    )
    assert response.status_code == 422
    assert "At most 100" in response.json()["detail"]


# --- submit_timecard: no entries ---


def test_submit_no_entries(auth_client, mock_fusion_catalogue):
    """Cover timecards.py:59 - empty entries list."""
    mock_fusion_catalogue.alist_assignments_for_worker.return_value = [
        {
            "workOrder": "WO-1",
            "projects": [{"projectNo": "P1", "projectName": "Alpha", "tasks": []}],
        }
    ]
    response = auth_client.post("/api/otl/timecard", json={"entries": []})
    assert response.status_code == 400
    assert "No timecard entries found" in response.json()["detail"]


# --- submit_timecard: idempotency key conflict ---


def test_submit_conflicting_idempotency_keys(auth_client, mock_fusion_catalogue):
    """Cover timecards.py:66-69 - conflicting requestId values."""
    mock_fusion_catalogue.alist_assignments_for_worker.return_value = [
        {
            "workOrder": "WO-1",
            "projects": [{"projectNo": "P1", "projectName": "Alpha", "tasks": []}],
        }
    ]
    response = auth_client.post(
        "/api/otl/timecard",
        json={"entries": [_entry()], "requestId": "req-1", "idempotencyKey": "req-2"},
        headers={"Idempotency-Key": "req-2"},
    )
    assert response.status_code == 400
    assert "Conflicting" in response.json()["detail"]


# --- submit_timecard: request_id in submit_kwargs ---


def test_submit_with_request_id_in_kwargs(
    auth_client, mock_fusion_catalogue, mock_otl_client
):
    """Cover timecards.py:134 - request_id added to submit_kwargs."""
    mock_fusion_catalogue.alist_assignments_for_worker.return_value = [
        {
            "workOrder": "WO-1",
            "projects": [{"projectNo": "P1", "projectName": "Alpha", "tasks": []}],
        }
    ]
    mock_otl_client.acreate_many.return_value = [
        {"index": 0, "ok": True, "id": "req-1"}
    ]
    response = auth_client.post(
        "/api/otl/timecard",
        json={"entries": [_entry()], "requestId": "req-1"},
    )
    assert response.status_code == 200
    # Verify acreate_many was called with request_id
    call_kwargs = mock_otl_client.acreate_many.call_args[1]
    assert "request_id" in call_kwargs
    assert call_kwargs["request_id"] == "req-1"


# --- submit_timecard: assignment lookup exception ---


def test_submit_assignment_lookup_exception(auth_client, mock_fusion_catalogue):
    """Cover timecards.py:105-107 - exception in alist_assignments_for_worker."""
    mock_fusion_catalogue.alist_assignments_for_worker.side_effect = RuntimeError(
        "boom"
    )
    with patch("backend.services.timecard_entries._STRICT_ASSIGNMENT_CACHE", True):
        response = auth_client.post("/api/otl/timecard", json={"entries": [_entry()]})
    assert response.status_code == 503
    assert "temporarily unavailable" in response.json()["detail"]


# --- submit_timecard: assignments is None (catalogue not loaded) ---


def test_submit_assignments_none(auth_client, mock_fusion_catalogue):
    """Cover timecards.py:115 - assignments_for_validation is None."""
    mock_fusion_catalogue.alist_assignments_for_worker.return_value = None
    with patch("backend.services.timecard_entries._STRICT_ASSIGNMENT_CACHE", True):
        response = auth_client.post("/api/otl/timecard", json={"entries": [_entry()]})
    assert response.status_code == 503
    assert "not loaded yet" in response.json()["detail"].lower()


# --- submit_timecard: validation error after assignments ---


def test_submit_validation_error_with_assignments(auth_client, mock_fusion_catalogue):
    """Cover timecards.py:95 - validation error after assignments lookup."""
    mock_fusion_catalogue.alist_assignments_for_worker.return_value = [
        {
            "workOrder": "WO-1",
            "projects": [{"projectNo": "P1", "projectName": "Alpha", "tasks": []}],
        }
    ]
    # Entry with task not in the project's tasks
    entry = _entry(taskId="NONEXISTENT")
    with patch("backend.services.timecard_entries._STRICT_ASSIGNMENT_CACHE", True):
        response = auth_client.post("/api/otl/timecard", json={"entries": [entry]})
    assert response.status_code == 400


# --- submit_timecard: submission exception (502) ---


def test_submit_submission_exception(
    auth_client, mock_fusion_catalogue, mock_otl_client
):
    """Cover timecards.py:139-147 - exception in acreate_many returns 502."""
    mock_fusion_catalogue.alist_assignments_for_worker.return_value = [
        {
            "workOrder": "WO-1",
            "projects": [{"projectNo": "P1", "projectName": "Alpha", "tasks": []}],
        }
    ]
    mock_otl_client.acreate_many.side_effect = RuntimeError("boom")
    response = auth_client.post("/api/otl/timecard", json={"entries": [_entry()]})
    assert response.status_code == 502
    assert "could not be completed" in response.json()["detail"]


# --- list_timecards: exception returns 502 ---


def test_list_timecards_exception(auth_client, mock_otl_client):
    """Cover timecards.py:188-193 - exception in alist_timecard_entries."""
    mock_otl_client.alist_timecard_entries.side_effect = RuntimeError("boom")
    response = auth_client.get("/api/otl/timecards")
    assert response.status_code == 502
    assert "Could not fetch timecards" in response.json()["detail"]


# --- list_timecards: project enrichment with PJC_PROJECT_ID ---


def test_list_timecards_enriches_project_comment(
    auth_client, mock_otl_client, mock_fusion_catalogue
):
    """Cover timecards.py:219-249 - project enrichment in list_timecards."""
    mock_otl_client.alist_timecard_entries.return_value = {
        "items": [
            {
                "timeRecordEvent": [
                    {
                        "timeRecordEventAttribute": [
                            {"attributeName": "PJC_PROJECT_ID", "attributeValue": "P1"},
                        ]
                    }
                ]
            }
        ]
    }
    mock_fusion_catalogue.get_project_by_id.return_value = {
        "project_id": "P1",
        "project_name": "Alpha Project",
    }
    response = auth_client.get("/api/otl/timecards")
    assert response.status_code == 200
    events = response.json()["items"][0]["timeRecordEvent"]
    attrs = events[0]["timeRecordEventAttribute"]
    comment_attrs = [a for a in attrs if a.get("attributeName") == "Comment"]
    assert len(comment_attrs) == 1
    assert "Alpha Project" in comment_attrs[0]["attributeValue"]


# --- list_timecards: no timeRecordEvent, top-level enrichment ---


def test_list_timecards_top_level_enrichment(
    auth_client, mock_otl_client, mock_fusion_catalogue
):
    """Cover timecards.py:229-247 - top-level item enrichment."""
    mock_otl_client.alist_timecard_entries.return_value = {
        "items": [
            {
                "timeAttributes": [
                    {"attributeName": "PJC_PROJECT_ID", "attributeValue": "P1"}
                ],
            }
        ]
    }
    mock_fusion_catalogue.get_project_by_id.return_value = {
        "project_id": "P1",
        "project_name": "Top Level Project",
    }
    response = auth_client.get("/api/otl/timecards")
    assert response.status_code == 200
    item = response.json()["items"][0]
    attrs = item["timeRecordEventAttribute"]
    comment_attrs = [a for a in attrs if a.get("attributeName") == "Comment"]
    assert len(comment_attrs) == 1
    assert "Top Level Project" in comment_attrs[0]["attributeValue"]


# --- list_timecards: item with existing comment ---


def test_list_timecards_existing_comment(
    auth_client, mock_otl_client, mock_fusion_catalogue
):
    """Cover timecards.py:248-254 - item with existing comment."""
    mock_otl_client.alist_timecard_entries.return_value = {
        "items": [
            {
                "timeAttributes": [
                    {"attributeName": "PJC_PROJECT_ID", "attributeValue": "P1"},
                    {"attributeName": "Comment", "attributeValue": "Existing comment"},
                ],
                "comment": "Item comment",
            }
        ]
    }
    mock_fusion_catalogue.get_project_by_id.return_value = {
        "project_id": "P1",
        "project_name": "Proj",
    }
    response = auth_client.get("/api/otl/timecards")
    assert response.status_code == 200
    item = response.json()["items"][0]
    attrs = item["timeRecordEventAttribute"]
    comment_attrs = [a for a in attrs if a.get("attributeName") == "Comment"]
    assert len(comment_attrs) == 1
    assert comment_attrs[0]["attributeValue"] == "Existing comment"


# --- labour_assignments: exception returns 503 ---


def test_labour_assignments_exception(auth_client, mock_fusion_catalogue):
    """Cover timecards.py:269-279 - exception in labour_assignments."""
    mock_fusion_catalogue.alist_assignments_for_worker.side_effect = RuntimeError(
        "boom"
    )
    response = auth_client.get("/api/labour/assignments")
    assert response.status_code == 503
    assert "temporarily unavailable" in response.json()["detail"]


# --- labour_assignments: work_orders is None ---


def test_labour_assignments_none(auth_client, mock_fusion_catalogue):
    """Cover timecards.py:281-287 - work_orders is None."""
    mock_fusion_catalogue.alist_assignments_for_worker.return_value = None
    response = auth_client.get("/api/labour/assignments")
    assert response.status_code == 503
    assert "still loading" in response.json()["detail"].lower()
