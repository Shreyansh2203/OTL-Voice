import time
from unittest.mock import MagicMock, patch

import pytest

import backend.services.fusion_catalogue as fc
from backend.services.fusion_catalogue import (
    _build_index,
    _client,
    _do_load_catalogue,
    _fetch_all_projects,
    _fetch_project_tasks,
    _fetch_project_team_members,
    _find_person_projects,
    _host_url,
    _ppm_base,
    catalogue_age_seconds,
    get_project_by_id,
    list_assignments_for_worker,
    load_catalogue,
    refresh_catalogue,
    status,
)


def test_build_index():
    projects_data = [
        {
            "project_id": "P1",
            "project_number": "1001",
            "project_name": "Alpha",
            "status": "Active",
            "manager": "Alice",
            "tasks": [{"taskId": "T1", "taskName": "Design"}],
            "team_members": [
                {"PersonName": "Bob Smith", "ProjectRole": "Developer"},
                {"PersonName": "Alice", "ProjectRole": "Manager"},
                {"PersonName": "", "ProjectRole": "Ghost"}  # To hit empty person_name condition line 142
            ]
        },
        {
            "project_id": "P2",
            "project_number": "1002",
            "project_name": "Beta",
            "status": "Active",
            "manager": "Alice",
            "tasks": [],
            "team_members": []
        }
    ]
    
    index = _build_index(projects_data)
    
    assert "bob smith" in index
    assert "alice" in index
    
    bob_projects = index["bob smith"]
    assert len(bob_projects) == 1
    assert bob_projects[0]["project_id"] == "P1"
    assert bob_projects[0]["project_name"] == "Alpha"
    assert bob_projects[0]["role"] == "Developer"
    assert len(bob_projects[0]["tasks"]) == 1

@patch('backend.services.otl_client.base_url')
def test_host_url_and_ppm_base(mock_base_url):
    mock_base_url.return_value = "https://fusion.example.com/some/path"
    assert _host_url() == "https://fusion.example.com"
    assert _ppm_base() == "https://fusion.example.com/fscmRestApi/resources/11.13.18.05"

@patch('backend.services.fusion_catalogue.httpx.Client')
@patch('backend.services.otl_client.service_credential')
def test_client(mock_service_credential, mock_client):
    mock_cred = MagicMock()
    mock_cred.auth = ("user", "pass")
    mock_service_credential.return_value = mock_cred
    _client()
    mock_client.assert_called_once()
    assert mock_client.call_args[1]['auth'] == ("user", "pass")

def test_fetch_all_projects():
    client = MagicMock()
    
    resp1 = MagicMock()
    resp1.status_code = 200
    resp1.json.return_value = {"items": [{"ProjectId": f"P{i}"} for i in range(100)]}
    
    resp2 = MagicMock()
    resp2.status_code = 200
    resp2.json.return_value = {"items": [{"ProjectId": f"P{i+100}"} for i in range(50)]}
    
    client.get.side_effect = [resp1, resp2]
    
    projects = _fetch_all_projects(client)
    assert len(projects) == 150
    
    resp_err = MagicMock()
    resp_err.status_code = 500
    resp_err.text = "Error"
    client.get.side_effect = [resp_err]
    assert _fetch_all_projects(client) == []
    
    resp_empty = MagicMock()
    resp_empty.status_code = 200
    resp_empty.json.return_value = {}
    client.get.side_effect = [resp_empty]
    assert _fetch_all_projects(client) == []

def test_fetch_project_tasks():
    client = MagicMock()
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"items": [{"TaskId": "T1"}]}
    client.get.return_value = resp
    
    assert _fetch_project_tasks(client, "P1") == [{"TaskId": "T1"}]
    
    resp_err = MagicMock()
    resp_err.status_code = 404
    client.get.return_value = resp_err
    assert _fetch_project_tasks(client, "P1") == []

def test_fetch_project_team_members():
    client = MagicMock()
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"items": [{"PersonName": "Bob"}]}
    client.get.return_value = resp
    
    assert _fetch_project_team_members(client, "P1") == [{"PersonName": "Bob"}]
    
    resp_err = MagicMock()
    resp_err.status_code = 404
    client.get.return_value = resp_err
    assert _fetch_project_team_members(client, "P1") == []

@patch('backend.services.fusion_catalogue._client')
@patch('backend.services.fusion_catalogue._fetch_all_projects')
@patch('backend.services.fusion_catalogue._fetch_project_tasks')
@patch('backend.services.fusion_catalogue._fetch_project_team_members')
def test_do_load_catalogue(mock_members, mock_tasks, mock_projects, mock_client):
    fc._is_loading = False
    
    # Normal execution with 10 projects to hit line 231
    mock_projects.return_value = [{"ProjectId": f"P{i}", "ProjectNumber": f"{i}", "ProjectName": f"A{i}", "ProjectManagerName": "Alice", "ProjectStatus": "Active"} for i in range(10)]
    mock_tasks.return_value = [{"TaskId": "T1", "TaskNumber": "1", "TaskName": "Task 1"}]
    mock_members.return_value = [{"PersonName": "Bob", "ProjectRole": "Dev"}]
    
    client_instance = MagicMock()
    mock_client.return_value = client_instance
    
    _do_load_catalogue()
    
    assert fc._is_loaded is True
    assert "bob" in fc._person_index
    assert "alice" in fc._person_index
    
    # Test fetch_project_details exception catching
    mock_tasks.side_effect = Exception("task error")
    fc._is_loading = False
    _do_load_catalogue()
    mock_tasks.side_effect = None
    
    # Already loading
    fc._is_loading = True
    _do_load_catalogue()
    
    # client error
    fc._is_loading = False
    mock_client.side_effect = Exception("error")
    _do_load_catalogue()
    assert fc._is_loading is False
    mock_client.side_effect = None
    
    # other error
    fc._is_loading = False
    mock_projects.side_effect = Exception("error")
    _do_load_catalogue()
    assert fc._is_loading is False
    mock_projects.side_effect = None

def test_load_catalogue():
    with patch('threading.Thread') as mock_thread:
        load_catalogue()
        mock_thread.assert_called_once()
        mock_thread.return_value.start.assert_called_once()

def test_get_project_by_id():
    fc._all_projects = [{"project_id": "P1"}]
    assert get_project_by_id("P1") == {"project_id": "P1"}
    assert get_project_by_id("P2") is None

def test_find_person_projects():
    fc._person_index = {"bob smith": [{"project_id": "P1"}]}
    assert _find_person_projects("Bob Smith") == [{"project_id": "P1"}]
    assert _find_person_projects("Bob") == [{"project_id": "P1"}]  # fuzzy
    assert _find_person_projects("smith") == [{"project_id": "P1"}]
    assert _find_person_projects("alice") == []

@patch('backend.services.fusion_catalogue.time.sleep')
def test_list_assignments_for_worker(mock_sleep):
    fc._is_loaded = False
    fc._is_loading = False
    assert list_assignments_for_worker("1", "Bob") == []
    
    def side_effect(*args):
        fc._is_loaded = True
    mock_sleep.side_effect = side_effect
    fc._is_loaded = False
    fc._is_loading = True
    # this will trip the loop and _is_loaded will become True
    assert list_assignments_for_worker("1", "Alice") == []
    
    fc._is_loaded = True
    fc._person_index = {
        "bob": [
            {
                "project_number": "1001",
                "project_id": "P1",
                "project_name": "A",
                "tasks": [{"task_number": "1", "task_id": "T1", "task_name": "T"}, {"task_number": None, "task_id": None, "task_name": "T3"}]
            },
            {
                "project_number": "NaN",  # Test value error
                "project_id": "P2",
                "project_name": "B",
                "tasks": [{"task_number": "NaN", "task_id": "NaN", "task_name": "T2"}]
            }
        ]
    }
    
    result = list_assignments_for_worker("1", "Bob")
    assert len(result) == 2
    assert result[0]["projects"][0]["projectNo"] == 1001
    assert result[0]["projects"][0]["tasks"][0]["taskId"] == 1
    assert result[0]["projects"][0]["tasks"][1]["taskId"] == 0
    assert result[1]["projects"][0]["projectNo"] == "NaN"
    assert result[1]["projects"][0]["tasks"][0]["taskId"] == "NaN"
    
    assert list_assignments_for_worker("1", "Alice") == []

def test_catalogue_age_seconds():
    fc._last_refresh = 0
    assert catalogue_age_seconds() is None
    
    fc._last_refresh = time.time() - 10
    assert 9 <= catalogue_age_seconds() <= 11

def test_status():
    st = status()
    assert "isLoaded" in st
    assert "isLoading" in st
    assert "totalProjects" in st

@pytest.mark.asyncio
async def test_refresh_catalogue():
    with patch('backend.services.fusion_catalogue.load_catalogue') as mock_load:
        fc._is_loading = False
        await refresh_catalogue()
        mock_load.assert_called_once()
        
        mock_load.reset_mock()
        fc._is_loading = True
        await refresh_catalogue()
        mock_load.assert_not_called()
