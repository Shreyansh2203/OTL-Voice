import sqlite3
import time
from unittest.mock import MagicMock, patch

from backend.services import fusion_catalogue
from backend.services.fusion_catalogue import (
    _build_index,
    _do_load_catalogue,
    _existing_projects,
    _FetchResult,
    catalogue_age_seconds,
    list_assignments_for_worker,
    refresh_catalogue,
    status,
)


def test_existing_projects_json_decode_error():
    """Cover fusion_catalogue.py:43-48 - _existing_projects JSON decode error."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE projects (project_id TEXT PRIMARY KEY, data JSON)")
    conn.execute(
        "INSERT INTO projects (project_id, data) VALUES ('P1', '{invalid json')"
    )
    conn.commit()
    result = _existing_projects(conn)
    assert result == {}


def test_existing_projects_non_dict():
    """Cover fusion_catalogue.py:47-48 - _existing_projects non-dict value."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE projects (project_id TEXT PRIMARY_KEY, data JSON)")
    conn.execute("INSERT INTO projects (project_id, data) VALUES ('P1', '[1,2,3]')")
    conn.commit()
    result = _existing_projects(conn)
    assert result == {}


def test_build_index_with_assignments():
    """Cover fusion_catalogue.py:113-148 - _build_index with assignments."""
    projects_data = [
        {
            "project_id": "P1",
            "project_number": "1001",
            "project_name": "Alpha",
            "status": "Active",
            "manager_id": "1",
            "tasks": [],
            "team_members": [],
        }
    ]
    assignments_data = [
        {
            "ProjectId": "P1",
            "ResourceHCMPersonId": "2",
            "ResourceName": "Bob",
        }
    ]
    index = _build_index(projects_data, assignments_data)
    assert "2" in index
    assert len(index["2"]) == 1
    assert index["2"][0]["role"] == "Resource Assignment"


def test_build_index_manager():
    """Cover fusion_catalogue.py:150-154 - _build_index manager indexing."""
    projects_data = [
        {
            "project_id": "P1",
            "project_number": "1001",
            "project_name": "Alpha",
            "status": "Active",
            "manager_id": "1",
            "manager": "Manager One",
            "tasks": [],
            "team_members": [],
        }
    ]
    index = _build_index(projects_data)
    assert "1" in index
    assert len(index["1"]) == 1
    assert index["1"][0]["role"] == "Project Manager"


def test_build_index_duplicate_identity_removed():
    """Cover fusion_catalogue.py:156-158 - _build_index removes ambiguous identity."""
    projects_data = [
        {
            "project_id": "P1",
            "project_number": "1001",
            "project_name": "Alpha",
            "status": "Active",
            "manager_id": "1",
            "tasks": [],
            "team_members": [
                {"PersonId": "2", "PersonName": "Bob", "ProjectRole": "Dev"},
                {"PersonId": "2", "PersonName": "Robert", "ProjectRole": "Mgr"},
            ],
        }
    ]
    index = _build_index(projects_data)
    assert "2" not in index


def test_do_load_catalogue_lock_stale():
    """Cover fusion_catalogue.py:166-174 - _do_load_catalogue stale lock."""
    import pathlib
    import tempfile

    tmp_dir = pathlib.Path(tempfile.mkdtemp())
    lock_path = tmp_dir / "catalogue.lock"
    try:
        old_time = time.time() - 7200
        lock_path.write_text(f"12345:{old_time}")

        with patch.object(fusion_catalogue, "_DB_PATH", tmp_dir / "catalogue.db"):
            with patch.object(fusion_catalogue, "_get_db", return_value=MagicMock()):
                with patch("backend.services.otl_client.service_credential"):
                    with patch.object(fusion_catalogue.httpx, "Client"):
                        with patch.object(
                            fusion_catalogue, "_fetch_all_projects"
                        ) as mock_fetch:
                            mock_fetch.return_value = _FetchResult(
                                complete=True, items=[]
                            )
                            _do_load_catalogue()

        # Lock should have been reclaimed
        assert not lock_path.exists()
    finally:
        import shutil

        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_do_load_catalogue_lock_acquire_error():
    """Cover fusion_catalogue.py:181-185 - _do_load_catalogue lock acquire error."""
    with patch.object(fusion_catalogue.os, "open", side_effect=PermissionError()):
        _do_load_catalogue()


def test_do_load_catalogue_credential_error():
    """Cover fusion_catalogue.py:214-231 - _do_load_catalogue credential/client error."""
    import pathlib
    import tempfile

    tmp_dir = pathlib.Path(tempfile.mkdtemp())
    try:
        with patch.object(fusion_catalogue, "_DB_PATH", tmp_dir / "catalogue.db"):
            with patch.object(fusion_catalogue, "_get_db", return_value=MagicMock()):
                with patch(
                    "backend.services.otl_client.service_credential",
                    side_effect=Exception("cred error"),
                ):
                    _do_load_catalogue()
    finally:
        import shutil

        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_do_load_catalogue_fetch_incomplete():
    """Cover fusion_catalogue.py:234-235 - _do_load_catalogue incomplete fetch."""
    import pathlib
    import tempfile

    tmp_dir = pathlib.Path(tempfile.mkdtemp())
    try:
        with patch.object(fusion_catalogue, "_DB_PATH", tmp_dir / "catalogue.db"):
            mock_conn = MagicMock()
            mock_conn.execute.return_value.fetchone.return_value = [0]
            with patch.object(fusion_catalogue, "_get_db", return_value=mock_conn):
                with patch("backend.services.otl_client.service_credential"):
                    mock_client = MagicMock()
                    with patch.object(
                        fusion_catalogue.httpx, "Client", return_value=mock_client
                    ):
                        with patch.object(
                            fusion_catalogue, "_fetch_all_projects"
                        ) as mock_fetch:
                            mock_fetch.return_value = _FetchResult(
                                complete=False, items=[]
                            )
                            _do_load_catalogue()
    finally:
        import shutil

        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_catalogue_age_seconds_no_meta():
    """Cover fusion_catalogue.py - catalogue_age_seconds with no meta."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.commit()
    with patch.object(fusion_catalogue, "_get_db", return_value=conn):
        assert catalogue_age_seconds() is None


def test_list_assignments_for_worker_not_loaded():
    """Cover fusion_catalogue.py - list_assignments_for_worker not loaded."""
    with patch.object(fusion_catalogue, "catalogue_age_seconds", return_value=None):
        result = list_assignments_for_worker("1", "Bob")
        assert result == []


def test_list_assignments_for_worker_empty_index():
    """Cover fusion_catalogue.py - list_assignments_for_worker empty index."""
    with patch.object(fusion_catalogue, "_build_index", return_value={}):
        with patch.object(fusion_catalogue, "_get_db") as mock_get_db:
            mock_conn = MagicMock()
            mock_conn.execute.return_value.fetchone.return_value = ["true"]
            mock_get_db.return_value = mock_conn
            result = list_assignments_for_worker("1", "Bob")
            assert result == []


def test_status_no_meta():
    """Cover fusion_catalogue.py - status with no meta table."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("CREATE TABLE projects (project_id TEXT PRIMARY KEY, data JSON)")
    conn.execute("CREATE TABLE person_index (name TEXT PRIMARY KEY, projects JSON)")
    conn.commit()
    with patch.object(fusion_catalogue, "_get_db", return_value=conn):
        st = status()
        assert "isLoaded" in st


def test_refresh_catalogue_loading():
    """Cover fusion_catalogue.py:404-409 - refresh_catalogue when already loading."""
    import asyncio

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES ('is_loading', 'true')"
    )
    conn.commit()

    with patch.object(fusion_catalogue, "_get_db", return_value=conn):
        with patch.object(fusion_catalogue, "load_catalogue") as mock_load:
            asyncio.run(refresh_catalogue())
            mock_load.assert_not_called()
