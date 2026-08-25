from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.main import (
    _extract_entries,
    _options_hint,
    _otl_config_error_handler,
    _otl_error_handler,
)
from backend.services.otl_client import OtlConfigError, OtlError


@pytest.fixture(autouse=True)
def disable_secure_cookies():
    with patch("backend.main.auth.cookie_secure", return_value=False):
        yield
@pytest.mark.asyncio
async def test_otl_error_handler():
    res = await _otl_error_handler(None, OtlError(status_code=400, message="bad"))
    assert res.status_code == 400
    res = await _otl_error_handler(None, OtlError(status_code=500, message="server"))
    assert res.status_code == 502
    res = await _otl_config_error_handler(None, OtlConfigError("bad"))
    assert res.status_code == 500
def test_speech_client_init():
    with patch("backend.main._speech_client"):
        from backend.main import _speech_client
    with patch("backend.services.oci_speech.SpeechClient"):
        from backend.main import _speech_client
        _speech_client.cache_clear()
        client = _speech_client()
        assert client is not None
def test_health(client):
    assert client.get("/api/health").status_code == 200
def test_health_otl(auth_client, mock_otl_client):
    mock_otl_client.avalidate.return_value = {"ok": True, "username": "test"}
    assert auth_client.get("/api/health/otl").status_code == 200
def test_session_unauthorized(client):
    assert client.get("/api/auth/session").status_code == 401
def test_login_success(client):
    response = client.post("/api/auth/login", json={"username": "testuser", "password": "dummy-password"})
    assert response.status_code == 200
    assert response.json()["username"] == "testuser"
    assert "otl_session" in response.headers.get("set-cookie", "").lower()
def test_login_failure(client):
    with patch("backend.main.otl_client.aget_worker", side_effect=Exception("error")):
        response = client.post("/api/auth/login", json={"username": "testuser", "password": "dummy-password"})
        assert response.status_code == 500
def test_login_not_found(client):
    with patch("backend.main.otl_client.aget_worker", return_value=None):
        response = client.post("/api/auth/login", json={"username": "testuser", "password": "dummy-password"})
        assert response.status_code == 401
def test_login_passwordless_success(client, mock_otl_client):
    mock_otl_client.aget_worker.return_value = {"personNumber": "208", "fullName": "Jessy Brown"}
    mock_otl_client.aget_worker.side_effect = None
    response = client.post("/api/auth/login", json={"username": "208", "password": ""})
    assert response.status_code == 200
    assert response.json()["fullName"] == "Jessy Brown"
    assert response.json()["username"] == "208"
def test_login_passwordless_not_found(client, mock_otl_client):
    mock_otl_client.aget_worker.return_value = None
    mock_otl_client.aget_worker.side_effect = None
    response = client.post("/api/auth/login", json={"username": "9999", "password": ""})
    assert response.status_code == 401
@pytest.fixture
def auth_client(client, mock_otl_client):
    mock_otl_client.aget_worker.return_value = {"personNumber": "testuser", "fullName": "Pytest User"}
    mock_otl_client.aget_worker.side_effect = None
    res = client.post("/api/auth/login", json={"username": "testuser", "password": "dummy-password"})
    assert res.status_code == 200
    return client
def test_session_authorized(auth_client):
    assert auth_client.get("/api/auth/session").status_code == 200
def test_logout(auth_client):
    response = auth_client.post("/api/auth/logout")
    assert response.status_code == 200
    assert "signed out" in response.json()["status"]
def test_chat_requires_auth(client):
    assert client.post("/api/chat", json={"messages": [{"role": "user", "content": "hello"}]}).status_code == 401
def test_chat_stream(auth_client):
    with patch("backend.main.chat.stream_sse") as mock_stream:
        mock_stream.return_value = iter(["data: hello\n\n"])
        response = auth_client.post("/api/chat", json={"messages": [{"role": "user", "content": "hello"}]})
        assert response.status_code == 200
        assert "hello" in response.text
def test_tts(auth_client):
    with patch("backend.main._speech_client") as mock_speech:
        mock_instance = MagicMock()
        mock_instance.synthesize.return_value = b"audio"
        mock_instance.mime = "audio/wav"
        mock_speech.return_value = mock_instance
        response = auth_client.post("/api/tts", json={"text": "hello"})
        assert response.status_code == 200
        assert response.content == b"audio"
def test_tts_error(auth_client):
    with patch("backend.main._speech_client") as mock_speech:
        mock_speech.return_value.synthesize.side_effect = Exception("error")
        assert auth_client.post("/api/tts", json={"text": "hello"}).status_code == 503
def test_extract_entries():
    assert _extract_entries("```json\n{\"entries\": [{\"a\": 1}]}\n```") == [{"a": 1}]
    assert _extract_entries("```json\n{invalid}\n```") == []
    assert _extract_entries("no json") == []
    assert _extract_entries("```json\n{\"other\": 1}\n```") == []
def test_submit_timecard_no_entries(auth_client):
    assert auth_client.post("/api/otl/timecard", json={}).status_code == 400
def test_submit_timecard(auth_client, mock_otl_client, mock_fusion_catalogue):
    mock_fusion_catalogue.alist_assignments_for_worker.return_value = [{
        "workOrder": "WO1",
        "projects": [{
            "projectId": 1,
            "projectNo": "P1",
            "projectName": "Proj 1",
            "tasks": [{"taskId": 10, "taskDetails": "Task 1"}]
        }]
    }]
    mock_otl_client.acreate_many.return_value = [{"ok": True}, {"ok": False}]
    response = auth_client.post("/api/otl/timecard", json={
        "entries": [
            {"projectNo": "P1", "taskDetails": "Task 1", "hours": 4},
            {"projectName": "Proj 1", "taskDetails": "Task 1", "hours": 2}
        ]
    })
    assert response.status_code == 200
    assert response.json()["submitted"] == 2
    assert response.json()["succeeded"] == 1
def test_submit_timecard_unknown_project(auth_client, mock_fusion_catalogue):
    mock_fusion_catalogue.alist_assignments_for_worker.return_value = []
    response = auth_client.post("/api/otl/timecard", json={"entries": [{"projectNo": "P99", "hours": 4, "taskDetails": "Task 1"}]})
    assert response.status_code == 400
    assert "not in your assigned projects" in response.text
def test_options_hint():
    assert _options_hint([]) == "You have no project assignments."
def test_options_hint_with_projects():
    assert _options_hint([{
        "workOrder": "WO1",
        "projects": [{"projectNo": "P1", "projectName": "Proj 1"}]
    }]) == "Assigned projects: P1 (Proj 1, WO WO1)."
def test_submit_timecard_not_strict(auth_client, mock_otl_client):
    with patch("backend.main._strict_assignment", return_value=False):
        mock_otl_client.acreate_many.return_value = [{"ok": True}]
        assert auth_client.post("/api/otl/timecard", json={"entries": [{"projectNo": "P99", "hours": 4, "taskDetails": "Task 1"}]}).status_code == 200
def test_list_timecards(auth_client, mock_otl_client, mock_fusion_catalogue):
    mock_otl_client.alist_timecard_entries.return_value = {
        "items": [{
            "timeRecordEvent": [{
                "timeRecordEventAttribute": [
                    {"attributeName": "PJC_PROJECT_ID", "attributeValue": "1"}
                ]
            }]
        }, {
            "timeRecordEvent": [{
                "timeRecordEventAttribute": [
                    {"attributeName": "Comment", "attributeValue": "already has comment"}
                ]
            }]
        }]
    }
    mock_fusion_catalogue.get_project_by_id.return_value = {"project_name": "Proj 1"}
    response = auth_client.get("/api/otl/timecards")
    assert response.status_code == 200
    attrs = response.json()["items"][0]["timeRecordEvent"][0]["timeRecordEventAttribute"]
    assert any(a.get("attributeName") == "Comment" for a in attrs)
def test_labour_assignments(auth_client, mock_fusion_catalogue):
    mock_fusion_catalogue.alist_assignments_for_worker.return_value = []
    assert auth_client.get("/api/labour/assignments").status_code == 200
@pytest.mark.asyncio
async def test_refresh_catalogue(auth_client, mock_fusion_catalogue):
    mock_fusion_catalogue.refresh_catalogue = AsyncMock()
    mock_fusion_catalogue.status.return_value = {"isLoaded": True, "isLoading": False, "totalProjects": 0, "totalPersonsIndexed": 0, "refreshIntervalSeconds": 21600}
    response = auth_client.post("/api/admin/refresh-catalogue")
    assert response.status_code == 200
def test_catalogue_status(auth_client, mock_fusion_catalogue):
    mock_fusion_catalogue.status.return_value = {"isLoaded": True, "isLoading": False, "totalProjects": 0, "totalPersonsIndexed": 0, "refreshIntervalSeconds": 21600}
    assert auth_client.get("/api/admin/catalogue-status").status_code == 200
def test_serve_spa(client):
    with patch("backend.main._DIST", new=None):
        assert client.get("/api/not-found").status_code == 404
    assert client.get("/index.html").status_code == 200
    assert client.get("/sw.js").status_code == 200
    assert client.get("/").status_code == 200
    assert client.get("/api/not-found").status_code == 404
def test_stt_stream_origin_validation_allowed():
    with patch("backend.main.auth.resolve", return_value=type("ctx", (), {"employee_id": "123", "username": "test", "full_name": "Test User"})()),         patch("backend.main.ws_tracker.acquire", return_value=True),         patch("backend.main.ws_tracker.release"),         patch("backend.main._cors_origins", return_value=["http://localhost:5173", "http://localhost:4173"]),         patch("backend.services.oci_speech.STTClient"):
        from fastapi.testclient import TestClient

        from backend.main import app
        with TestClient(app) as client:
            with client.websocket_connect("/api/stt/stream", headers={"Origin": "http://localhost:5173"}) as _:
                pass
def test_stt_stream_origin_validation_blocked():
    with patch("backend.main.auth.resolve", return_value=type("ctx", (), {"employee_id": "123", "username": "test", "full_name": "Test User"})()),         patch("backend.main.ws_tracker.acquire", return_value=True),         patch("backend.main.ws_tracker.release"),         patch("backend.main._cors_origins", return_value=["http://localhost:5173", "http://localhost:4173"]):
        from fastapi.testclient import TestClient

        from backend.main import app
        with TestClient(app) as client:
            try:
                with client.websocket_connect("/api/stt/stream", headers={"Origin": "http://evil.com"}):
                    pass
                assert False, "Expected WebSocketDisconnect"
            except Exception as e:
                assert hasattr(e, 'code') and e.code == 1008, f"Expected code 1008, got {getattr(e, 'code', None)}"
def test_stt_stream_origin_validation_sec_websocket_origin():
    with patch("backend.main.auth.resolve", return_value=type("ctx", (), {"employee_id": "123", "username": "test", "full_name": "Test User"})()),         patch("backend.main.ws_tracker.acquire", return_value=True),         patch("backend.main.ws_tracker.release"),         patch("backend.main._cors_origins", return_value=["http://localhost:5173", "http://localhost:4173"]),         patch("backend.services.oci_speech.STTClient"):
        from fastapi.testclient import TestClient

        from backend.main import app
        with TestClient(app) as client:
            with client.websocket_connect("/api/stt/stream", headers={"Sec-WebSocket-Origin": "http://localhost:5173"}) as _:
                pass