import json
import sqlite3
import time
from unittest.mock import MagicMock, patch
import pytest
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
@pytest.fixture(autouse=True)
def mock_db():
    conn = sqlite3.connect("file:memdb1?mode=memory&cache=shared", uri=True, check_same_thread=False)
    conn.execute('''CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS projects (project_id TEXT PRIMARY KEY, data JSON)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS person_index (name TEXT PRIMARY KEY, projects JSON)''')
    conn.commit()
    def _mock_get_db():
        return sqlite3.connect("file:memdb1?mode=memory&cache=shared", uri=True, check_same_thread=False)
    with patch('backend.services.fusion_catalogue._get_db', side_effect=_mock_get_db):
        yield conn
    conn.close()
@pytest.fixture(autouse=True)
def clear_db(mock_db):
    mock_db.execute("DELETE FROM projects")
    mock_db.execute("DELETE FROM person_index")
    mock_db.execute("DELETE FROM meta")
    mock_db.commit()
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
                {"PersonName": "", "ProjectRole": "Ghost"}
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
def test_fetch_project_tasks():
    client = MagicMock()
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"items": [{"TaskId": "T1"}]}
    client.get.return_value = resp
    assert _fetch_project_tasks(client, "P1") == [{"TaskId": "T1"}]
def test_fetch_project_team_members():
    client = MagicMock()
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"items": [{"PersonName": "Bob"}]}
    client.get.return_value = resp
    assert _fetch_project_team_members(client, "P1") == [{"PersonName": "Bob"}]
@patch('backend.services.fusion_catalogue._client')
@patch('backend.services.fusion_catalogue._fetch_all_projects')
@patch('backend.services.fusion_catalogue._fetch_project_tasks')
@patch('backend.services.fusion_catalogue._fetch_project_team_members')
@patch('backend.services.fusion_catalogue._fetch_all_resource_assignments')
@patch('backend.services.otl_client.service_credential')
def test_do_load_catalogue(mock_service_credential, mock_assignments, mock_members, mock_tasks, mock_projects, mock_client, mock_db):
    mock_cred = MagicMock()
    mock_cred.auth = ("user", "pass")
    mock_service_credential.return_value = mock_cred
    mock_projects.return_value = [{"ProjectId": f"P{i}", "ProjectNumber": f"{i}", "ProjectName": f"A{i}", "ProjectManagerName": "Alice", "ProjectStatus": "Active"} for i in range(10)]
    mock_tasks.return_value = [{"TaskId": "T1", "TaskNumber": "1", "TaskName": "Task 1"}]
    mock_members.return_value = [{"PersonName": "Bob", "ProjectRole": "Dev"}]
    mock_assignments.return_value = []
    client_instance = MagicMock()
    mock_client.return_value = client_instance
    _do_load_catalogue()
    cur = mock_db.execute("SELECT value FROM meta WHERE key = 'is_loaded'")
    assert cur.fetchone()[0] == 'true'
    cur = mock_db.execute("SELECT name FROM person_index")
    names = [row[0] for row in cur.fetchall()]
    assert "bob" in names
    assert "alice" in names
def test_load_catalogue():
    with patch('threading.Thread') as mock_thread:
        load_catalogue()
        mock_thread.assert_called_once()
        mock_thread.return_value.start.assert_called_once()
def test_get_project_by_id(mock_db):
    mock_db.execute("INSERT INTO projects (project_id, data) VALUES (?, ?)", ("P1", json.dumps({"project_id": "P1"})))
    mock_db.commit()
    assert get_project_by_id("P1") == {"project_id": "P1"}
    assert get_project_by_id("P2") is None
def test_find_person_projects(mock_db):
    mock_db.execute("INSERT INTO person_index (name, projects) VALUES (?, ?)", ("bob smith", json.dumps([{"project_id": "P1"}])))
    mock_db.commit()
    assert _find_person_projects("Bob Smith") == [{"project_id": "P1"}]
    assert _find_person_projects("Bob") == [{"project_id": "P1"}]
    assert _find_person_projects("smith") == [{"project_id": "P1"}]
    assert _find_person_projects("alice") == []
@patch('backend.services.fusion_catalogue.time.sleep')
def test_list_assignments_for_worker(mock_sleep, mock_db):
    assert list_assignments_for_worker("1", "Bob") == []
    mock_db.execute("INSERT INTO meta (key, value) VALUES ('is_loaded', 'true')")
    mock_db.execute("INSERT INTO person_index (name, projects) VALUES (?, ?)", ("bob", json.dumps([
        {
            "project_number": "1001",
            "project_id": "P1",
            "project_name": "A",
            "tasks": [{"task_number": "1", "task_id": "T1", "task_name": "T"}, {"task_number": None, "task_id": None, "task_name": "T3"}]
        }
    ])))
    mock_db.commit()
    result = list_assignments_for_worker("1", "Bob")
    assert len(result) == 1
    assert result[0]["projects"][0]["projectNo"] == 1001
    assert result[0]["projects"][0]["tasks"][0]["taskId"] == 1
def test_catalogue_age_seconds(mock_db):
    assert catalogue_age_seconds() is None
    mock_db.execute("INSERT INTO meta (key, value) VALUES ('last_refresh', ?)", (str(time.time() - 10),))
    mock_db.commit()
    assert 9 <= catalogue_age_seconds() <= 11
def test_status(mock_db):
    st = status()
    assert "isLoaded" in st
    assert "isLoading" in st
    assert "totalProjects" in st
@pytest.mark.asyncio
async def test_refresh_catalogue(mock_db):
    with patch('backend.services.fusion_catalogue.load_catalogue') as mock_load:
        mock_db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('is_loading', 'false')")
        mock_db.commit()
        await refresh_catalogue()
        mock_load.assert_called_once()
        mock_load.reset_mock()
        mock_db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('is_loading', 'true')")
        mock_db.commit()
        await refresh_catalogue()
        mock_load.assert_not_called()