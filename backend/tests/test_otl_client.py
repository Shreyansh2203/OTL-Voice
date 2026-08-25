import os
from unittest.mock import MagicMock, patch
import pytest
from backend.services.otl_client import (
    OtlConfigError,
    OtlCredential,
    OtlError,
    _clip,
    _coerce_number,
    _default_record_name,
    _extract_error,
    _raise_for_status,
    _safe_body,
    _timeout,
    acreate_many,
    base_url,
    create_timecard_entry,
    delete_timecard_entry,
    escape_q_literal,
    get_timecard_entry,
    get_worker,
    hcm_base_url,
    list_timecard_entries,
    list_worker_assignments,
    map_entry_to_otl,
    service_credential,
    validate,
)
def test_base_url_missing():
    with patch.dict(os.environ, clear=True):
        with pytest.raises(ValueError, match="OTL_BASE_URL environment variable is not set"):
            base_url()
def test_base_url_present():
    with patch.dict(os.environ, {"OTL_BASE_URL": "http://example.com/"}):
        assert base_url() == "http://example.com"
def test_timeout():
    with patch.dict(os.environ, {"OTL_TIMEOUT_SECONDS": "42.0"}):
        timeout = _timeout()
        assert timeout.read == 42.0
def test_otl_error():
    err = OtlError(404, "Not Found", detail="xyz")
    assert err.status_code == 404
    assert err.message == "Not Found"
    assert err.detail == "xyz"
    assert str(err) == "Not Found"
def test_service_credential_missing():
    with patch.dict(os.environ, clear=True), pytest.raises(OtlConfigError):
        service_credential()
    with patch.dict(os.environ, {"OTL_SERVICE_USERNAME": "u"}, clear=True):
        with pytest.raises(OtlConfigError):
            service_credential()
def test_service_credential_present():
    with patch.dict(os.environ, {"OTL_SERVICE_USERNAME": " u ", "OTL_SERVICE_PASSWORD": "p"}):
        cred = service_credential()
        assert cred.username == "u"
        assert cred.password == "p"
def test_extract_error():
    resp = MagicMock()
    resp.json.return_value = {"detail": "Err1"}
    assert _extract_error(resp) == "Err1"
    resp.json.return_value = {"title": "Err2"}
    assert _extract_error(resp) == "Err2"
    resp.json.return_value = {"message": "Err3"}
    assert _extract_error(resp) == "Err3"
    resp.json.side_effect = Exception("JSON parse error")
    resp.text = " Text Error "
    assert _extract_error(resp) == "Text Error"
    resp.text = ""
    resp.status_code = 500
    assert _extract_error(resp) == "OTL request failed with HTTP 500"
def test_raise_for_status():
    resp = MagicMock()
    resp.status_code = 200
    _raise_for_status(resp) 
    resp.status_code = 400
    resp.json.return_value = {"detail": "Bad Request"}
    with pytest.raises(OtlError) as exc:
        _raise_for_status(resp)
    assert exc.value.status_code == 400
    assert exc.value.message == "Bad Request"
def test_safe_body():
    resp = MagicMock()
    resp.json.return_value = {"a": 1}
    assert _safe_body(resp) == {"a": 1}
    resp.json.side_effect = Exception("JSON error")
    resp.text = "a" * 3000
    assert len(_safe_body(resp)) == 3000
def test_coerce_number():
    assert _coerce_number(None) is None
    assert _coerce_number("") is None
    assert _coerce_number("4.6") == 5
    assert _coerce_number("7.5") == 8
    assert _coerce_number(8.0) == 8
    assert _coerce_number(8) == 8
    assert _coerce_number("abc") is None
def test_clip():
    assert _clip(None) is None
    long_str = "a" * 100
    assert len(_clip(long_str)) == 80
def test_map_entry_to_otl():
    with pytest.raises(OtlError, match="must be greater than zero"):
        map_entry_to_otl({"hours": 0})
    entry = {
        "employeeNumber": "123",
        "hours": 8,
        "date": "2024-05-10",
        "startTime": "09:00",
        "stopTime": "17:00",
        "projectName": "Proj1",
        "projectNo": "P1",
        "taskDetails": "Task1",
        "workOrder": "WO1",
        "payrollTimeType": "Regular",
        "projectId": "PROJ-123",
        "taskId": "TASK-123",
        "expenditureType": "Dev"
    }
    with patch("backend.services.otl_client.datetime") as mock_dt:
        mock_dt.now.return_value.replace.return_value = None 
        out = map_entry_to_otl(entry)
    assert out["processInline"] == "Y"
    ev = out["timeRecordEvent"][0]
    assert ev["measure"] == 8
    assert ev["reporterId"] == "123"
    attrs = {a["attributeName"]: a["attributeValue"] for a in ev["timeRecordEventAttribute"]}
    assert attrs["PayrollTimeType"] == "Regular"
    assert attrs["PJC_PROJECT_ID"] == "PROJ-123"
    assert attrs["PJC_TASK_ID"] == "TASK-123"
    assert attrs["PJC_EXPENDITURE_TYPE_NAME"] == "Dev"
    assert "Proj1 (P1) | Task: Task1 | WO: WO1 | Total Hours: 8" in attrs["Comment"]
    with pytest.raises(OtlError, match="Invalid date format"):
        map_entry_to_otl({"hours": 8, "date": "bad-date"})
    out_empty = map_entry_to_otl({"hours": 8})
    ev2 = out_empty["timeRecordEvent"][0]
    assert ev2["reporterId"] == "UNKNOWN_EMP"
    entry3 = {"hours": 8, "date": "2024-05-10", "startTime": "bad-time", "stopTime": "bad-time"}
    out3 = map_entry_to_otl(entry3)
    ev3 = out3["timeRecordEvent"][0]
    assert "T09:00" in ev3["startTime"] 
def test_default_record_name():
    assert "EMP-WO-" in _default_record_name({})
    assert "123-WO1-" in _default_record_name({"employeeNumber": " 123 ", "workOrder": " WO1 "})
@patch("httpx.Client.get")
def test_validate(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_get.return_value = mock_resp
    cred = OtlCredential("u", "p")
    with patch.dict(os.environ, {"OTL_BASE_URL": "http://x"}):
        res = validate(cred)
        assert res["ok"] is True
    mock_resp.status_code = 401
    with pytest.raises(OtlError, match="rejected the service account credential"):
        with patch.dict(os.environ, {"OTL_BASE_URL": "http://x"}):
            validate(cred)
def test_escape_q_literal():
    assert escape_q_literal("O'Connor") == "O''Connor"
@patch("httpx.Client.get")
def test_list_timecard_entries(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"items": []}
    mock_get.return_value = mock_resp
    cred = OtlCredential("u", "p")
    with patch.dict(os.environ, {"OTL_BASE_URL": "http://x"}):
        res = list_timecard_entries(cred, query="test")
        assert res == {"items": []}
        mock_get.assert_called_once()
        _args, kwargs = mock_get.call_args
        assert kwargs["params"]["q"] == "test"
def test_hcm_base_url():
    with patch.dict(os.environ, {"OTL_BASE_URL": "http://x/timeRecordEventRequests"}):
        assert hcm_base_url() == "http://x"
    with patch.dict(os.environ, {"OTL_BASE_URL": "http://x/other"}):
        assert hcm_base_url() == "http://x/other"
@patch("httpx.Client.get")
def test_get_worker_success(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "items": [
            {
                "PersonId": "P1",
                "PersonNumber": "123", 
                "names": {"items": [{"DisplayName": "Test User"}]}
            }
        ]
    }
    mock_get.return_value = mock_resp
    cred = OtlCredential("test", "pass")
    with patch.dict(os.environ, {"OTL_BASE_URL": "http://x"}):
        worker = get_worker(cred, "123")
    assert worker is not None
    assert worker["personNumber"] == "123"
    assert worker["fullName"] == "Test User"
@patch("httpx.Client.get")
def test_get_worker_empty(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"items": []}
    mock_get.return_value = mock_resp
    cred = OtlCredential("test", "pass")
    with patch.dict(os.environ, {"OTL_BASE_URL": "http://x"}):
        assert get_worker(cred, "123") is None
@patch("backend.services.fusion_catalogue.list_assignments_for_worker")
def test_list_worker_assignments(mock_list):
    mock_list.return_value = [{"assignmentId": "A1", "assignmentName": "Test Assignment"}]
    cred = OtlCredential("test", "pass")
    assignments = list_worker_assignments(cred, "123", "Test User")
    assert len(assignments) == 1
    assert assignments[0]["assignmentId"] == "A1"
@patch("httpx.Client.get")
def test_get_timecard_entry(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"id": "1"}
    mock_get.return_value = mock_resp
    cred = OtlCredential("u", "p")
    with patch.dict(os.environ, {"OTL_BASE_URL": "http://x"}):
        res = get_timecard_entry(cred, "1")
        assert res["id"] == "1"
@patch("httpx.Client.post")
def test_create_timecard_entry(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"timeRecordEventRequestId": "req1"}
    mock_post.return_value = mock_resp
    cred = OtlCredential("u", "p")
    with patch.dict(os.environ, {"OTL_BASE_URL": "http://x"}):
        res = create_timecard_entry(cred, {"hours": 5})
        assert res["timeRecordEventRequestId"] == "req1"
@patch("httpx.Client.delete")
def test_delete_timecard_entry(mock_delete):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_delete.return_value = mock_resp
    cred = OtlCredential("u", "p")
    with patch.dict(os.environ, {"OTL_BASE_URL": "http://x"}):
        delete_timecard_entry(cred, "1")
@patch("backend.services.otl_client.acreate_timecard_entry")
@pytest.mark.asyncio
async def test_create_many(mock_create):
    mock_create.side_effect = [
        {"timeRecordEventRequestId": "req1"},
        OtlError(400, "Bad Request")
    ]
    cred = OtlCredential("u", "p")
    results = await acreate_many(cred, [{"hours": 5}, {"hours": -1}])
    assert len(results) == 2
    assert results[0]["ok"] is True
    assert results[0]["id"] == "req1"
    assert results[1]["ok"] is False
    assert results[1]["error"] == "Bad Request"