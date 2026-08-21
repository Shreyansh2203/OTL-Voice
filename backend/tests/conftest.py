import os
import sys
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# Mock the env vars before loading main
os.environ["OTL_SERVICE_USERNAME"] = "mock_user"
os.environ["OTL_SERVICE_PASSWORD"] = "mock_pass"
os.environ["OTL_BASE_URL"] = "https://mock.example.com"
os.environ["OCI_CONFIG_PROFILE"] = "DEFAULT"

# Add the root directory to PYTHONPATH so backend can be imported
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
        mock.get_worker.return_value = {
            "personNumber": "testuser",
            "fullName": "Test User"
        }
        yield mock

@pytest.fixture(autouse=True)
def mock_fusion_catalogue():
    with patch("backend.main.fusion_catalogue") as mock:
        yield mock
