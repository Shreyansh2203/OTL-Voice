import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi.testclient import TestClient
os.environ["OTL_SERVICE_USERNAME"] = "mock_user"
os.environ["OTL_SERVICE_PASSWORD"] = "mock_pass"
os.environ["OTL_BASE_URL"] = "https://mock.example.com"
os.environ["OCI_CONFIG_PROFILE"] = "DEFAULT"
os.environ["SESSION_SECRET_KEY"] = "test-secret-key-for-testing-only"
os.environ["CSP_DEV_MODE"] = "true"
os.environ["TEST_MODE"] = "true"  
os.environ["SESSION_COOKIE_SECURE"] = "false"  
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from backend.main import app
@pytest.fixture
def client():
    with TestClient(app) as client:
        yield client
@pytest.fixture(autouse=True)
def mock_otl_client():
    with patch("backend.main.otl_client") as mock:
        mock.list_worker_assignments.return_value = []
        mock.aget_worker = AsyncMock(return_value={"personNumber": "testuser", "fullName": "Test User"})
        mock.get_worker.return_value = {
            "personNumber": "testuser",
            "fullName": "Test User"
        }
        mock.alist_assignments_for_worker = AsyncMock(return_value=[])
        mock.acreate_many = AsyncMock(return_value=[{"ok": True}])
        mock.alist_timecard_entries = AsyncMock(return_value={"items": []})
        mock.validate.return_value = {"ok": True, "username": "test"}
        mock.validate.side_effect = None
        mock.avalidate = AsyncMock(return_value={"ok": True, "username": "test"})
        yield mock
@pytest.fixture(autouse=True)
def mock_fusion_catalogue():
    with patch("backend.main.fusion_catalogue") as mock:
        mock.alist_assignments_for_worker = AsyncMock(return_value=[])
        mock.refresh_catalogue = AsyncMock()
        mock.status.return_value = {"isLoaded": True, "isLoading": False, "totalProjects": 0, "totalPersonsIndexed": 0, "refreshIntervalSeconds": 21600}
        mock.get_project_by_id = MagicMock(return_value=None)
        yield mock
@pytest.fixture(autouse=True)
def mock_speech_client():
    with patch("backend.main._speech_client") as mock:
        mock_instance = mock.return_value
        mock_instance.synthesize.return_value = b"audio"
        mock_instance.mime = "audio/wav"
        yield mock