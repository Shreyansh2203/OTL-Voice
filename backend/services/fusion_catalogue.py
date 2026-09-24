"""
Fusion Live Catalogue
======================
Fetches projects, tasks, and team-member allocations directly from Oracle
Fusion Cloud REST APIs on startup, caches them in a local SQLite database, and provides
fast lookups by employee name.
Using SQLite allows multiple Uvicorn workers to share the catalogue without duplicating
memory usage or fragmenting state.
The catalogue auto-refreshes on a configurable interval (default: 6 hours).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

import httpx

from . import fusion_catalogue_client as _client_module

_FetchResult = _client_module._FetchResult
_CatalogueFetchError = _client_module._CatalogueFetchError
_fetch_complete = _client_module._fetch_complete
_has_more = _client_module._has_more
_host_url = _client_module._host_url
_ppm_base = _client_module._ppm_base
_client = _client_module._client
_fetch_all_projects = _client_module._fetch_all_projects
_fetch_child_items = _client_module._fetch_child_items
_fetch_project_tasks = _client_module._fetch_project_tasks
_fetch_project_team_members = _client_module._fetch_project_team_members
_fetch_all_resource_assignments = _client_module._fetch_all_resource_assignments

logger = logging.getLogger(__name__)
_REFRESH_INTERVAL = int(os.getenv("CATALOGUE_REFRESH_SECONDS", str(6 * 3600)))
_DB_PATH = Path(__file__).parent.parent.parent / "data" / "catalogue.db"
_thread_local = threading.local()
_load_lock = threading.Lock()
_is_loading = False


def _existing_projects(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    rows = conn.execute("SELECT project_id, data FROM projects").fetchall()
    result: dict[str, dict[str, Any]] = {}
    for project_id, data in rows:
        try:
            value = json.loads(data)
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            result[str(project_id)] = value
    return result


def _get_db() -> sqlite3.Connection:
    if not hasattr(_thread_local, "conn") or _thread_local.conn is None:
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS projects (project_id TEXT PRIMARY KEY, data JSON)"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS person_index (name TEXT PRIMARY KEY, projects JSON)"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS projects_staging (project_id TEXT PRIMARY KEY, data JSON)"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS person_index_staging (name TEXT PRIMARY KEY, projects JSON)"""
        )
        conn.commit()
        _thread_local.conn = conn
    return _thread_local.conn


def _close_db() -> None:
    if hasattr(_thread_local, "conn") and _thread_local.conn is not None:
        _thread_local.conn.close()
        _thread_local.conn = None


def _build_index(
    projects_data: list[dict], assignments_data: list[dict] | None = None
) -> dict[str, list[dict]]:
    index: dict[str, list[dict]] = {}
    seen_projects: dict[str, set[str]] = {}
    if assignments_data is None:
        assignments_data = []

    def _add_to_index(key: str, entry: dict) -> None:
        k = key.strip().lower()
        if not k:
            return
        if k not in index:
            index[k] = []
            seen_projects[k] = set()
        if entry["project_number"] not in seen_projects[k]:
            seen_projects[k].add(entry["project_number"])
            index[k].append(entry)

    for proj in projects_data:
        proj_entry = {
            "project_id": str(proj.get("project_id", "")),
            "project_number": str(proj.get("project_number", "")),
            "project_name": proj.get("project_name", ""),
            "status": proj.get("status", ""),
            "manager": proj.get("manager", ""),
            "tasks": proj.get("tasks", []),
        }
        for member in proj.get("team_members", []):
            person_id = str(
                member.get("HCMPersonId") or member.get("PersonId") or ""
            ).strip()
            member_name = str(
                member.get("PersonName") or member.get("TeamMemberName") or ""
            ).strip()
            member_entry = {
                **proj_entry,
                "role": member.get("ProjectRole", "Team Member"),
            }
            if person_id:
                _add_to_index(person_id, member_entry)
            if member_name:
                _add_to_index(member_name, member_entry)

        for assign in assignments_data:
            if str(assign.get("ProjectId")) == proj_entry["project_id"]:
                person_id = str(assign.get("ResourceHCMPersonId") or "").strip()
                res_name = str(assign.get("ResourceName") or "").strip()
                assign_entry = {
                    **proj_entry,
                    "role": "Resource Assignment",
                }
                if person_id:
                    _add_to_index(person_id, assign_entry)
                if res_name:
                    _add_to_index(res_name, assign_entry)

        mgr_id = str(proj.get("manager_id") or "").strip()
        mgr_name = str(proj.get("manager") or "").strip()
        mgr_entry = {
            **proj_entry,
            "role": "Project Manager",
        }
        if mgr_id:
            _add_to_index(mgr_id, mgr_entry)
        if mgr_name:
            _add_to_index(mgr_name, mgr_entry)

    return index


def _do_load_catalogue() -> None:
    lock_path = _DB_PATH.with_suffix(".lock")
    try:
        if lock_path.exists():
            try:
                content = lock_path.read_text()
                _pid, ts = content.split(":")
                if time.time() - float(ts) > 3600:
                    logger.warning("Found stale lock file, reclaiming...")
                    lock_path.unlink()
            except Exception:
                pass
        lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(lock_fd, f"{os.getpid()}:{time.time()}".encode())
        os.close(lock_fd)
    except FileExistsError:
        logger.warning("Catalogue load already in progress by another worker")
        return
    except Exception:
        logger.exception("Failed to acquire loading lock")
        return
    conn = _get_db()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('is_loading', 'true')"
        )
        conn.commit()
    except Exception:
        logger.exception("Failed to set loading state")
        try:
            os.unlink(lock_path)
        except Exception:
            pass
        return
    logger.info("Loading Fusion catalogue from live APIs...")
    start = time.time()
    try:
        from . import otl_client

        cred = otl_client.service_credential()
        client = httpx.Client(
            auth=cred.auth,
            timeout=httpx.Timeout(60.0, connect=15.0),
            headers={"Accept": "application/json", "Accept-Encoding": "gzip"},
        )
    except Exception as e:
        logger.error("Cannot create Fusion API client: %s", e)
        try:
            os.unlink(lock_path)
        except Exception:
            pass
        try:
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('is_loading', 'false')"
            )
            conn.commit()
        except Exception:
            pass
        return
    try:
        raw_projects = _fetch_all_projects(client)
        if not _fetch_complete(raw_projects):
            raise _CatalogueFetchError("Fusion project catalogue fetch was incomplete")
        if not raw_projects:
            existing_count = conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
            if existing_count:
                raise _CatalogueFetchError(
                    "Fusion project catalogue fetch returned no data"
                )
        logger.info("Fetched %d projects total.", len(raw_projects))
        import concurrent.futures

        existing_projects = _existing_projects(conn)
        enriched = []
        details_complete = True

        def create_client() -> httpx.Client:
            from . import otl_client

            cred = otl_client.service_credential()
            return httpx.Client(
                auth=cred.auth,
                timeout=httpx.Timeout(60.0, connect=15.0),
                headers={"Accept": "application/json", "Accept-Encoding": "gzip"},
            )

        def fetch_project_details(p):
            thread_client = create_client()
            try:
                p_id = str(p.get("ProjectId", "")).strip()
                if not p_id:
                    raise _CatalogueFetchError("Project response omitted ProjectId")
                p_num = str(p.get("ProjectNumber", ""))
                p_name = p.get("ProjectName", "")
                tasks = _fetch_project_tasks(thread_client, p_id)
                members = _fetch_project_team_members(thread_client, p_id)
                if not _fetch_complete(tasks) or not _fetch_complete(members):
                    raise _CatalogueFetchError(
                        f"Project detail fetch was incomplete for {p_id}"
                    )
                old_project = existing_projects.get(p_id, {})
                if not tasks and old_project.get("tasks"):
                    raise _CatalogueFetchError(
                        f"Project task fetch returned partial data for {p_id}"
                    )
                if not members and old_project.get("team_members"):
                    raise _CatalogueFetchError(
                        f"Project team fetch returned partial data for {p_id}"
                    )
                return {
                    "project_id": p_id,
                    "project_number": p_num,
                    "project_name": p_name,
                    "status": p.get("ProjectStatus", ""),
                    "manager": p.get("ProjectManagerName", ""),
                    "manager_id": str(
                        p.get("ProjectManagerId") or p.get("ProjectManagerEmail") or ""
                    ).strip(),
                    "tasks": [
                        {
                            "task_id": str(t.get("TaskId", "")),
                            "task_number": str(t.get("TaskNumber", "")),
                            "task_name": t.get("TaskName", ""),
                        }
                        for t in tasks
                    ],
                    "team_members": members,
                }
            finally:
                thread_client.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            future_to_proj = {
                executor.submit(fetch_project_details, p): p for p in raw_projects
            }
            for i, future in enumerate(concurrent.futures.as_completed(future_to_proj)):
                try:
                    enriched.append(future.result())
                except Exception as exc:
                    details_complete = False
                    logger.error(
                        "Project details fetch generated an exception: %s", exc
                    )
                if (i + 1) % 10 == 0:
                    logger.info(
                        "  Enriched %d/%d projects...", i + 1, len(raw_projects)
                    )
        if not details_complete or len(enriched) != len(raw_projects):
            raise _CatalogueFetchError("Some Fusion project details were unavailable")
        logger.info("Fetched details for %d projects.", len(enriched))
        logger.info("Fetching project resource assignments...")
        assignments = _fetch_all_resource_assignments(client)
        if not _fetch_complete(assignments):
            raise _CatalogueFetchError(
                "Fusion resource assignment fetch was incomplete"
            )
        if not assignments:
            existing_count = max(
                conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0],
                conn.execute("SELECT COUNT(*) FROM person_index").fetchone()[0],
            )
            if existing_count:
                raise _CatalogueFetchError(
                    "Fusion resource assignment fetch returned no data"
                )
        logger.info("Fetched %d resource assignments.", len(assignments))
        logger.info("Building project index...")
        person_index = _build_index(enriched, assignments_data=assignments)
        _save_catalogue(conn, enriched, person_index)

        elapsed = time.time() - start
        logger.info(
            "Fusion catalogue ready: %d projects, %d persons indexed (%.1fs)",
            len(enriched),
            len(person_index),
            elapsed,
        )
    except _CatalogueFetchError as exc:
        logger.error("Keeping existing Fusion catalogue: %s", exc)
    except Exception:
        logger.exception("Failed to load Fusion catalogue; keeping existing catalogue")
    finally:
        client.close()
        _set_loading_false(conn, lock_path)


def _set_loading_false(conn: sqlite3.Connection, lock_path: Path) -> None:
    global _is_loading
    try:
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('is_loading', 'false')"
        )
        conn.commit()
    except Exception:
        pass
    try:
        os.unlink(lock_path)
    except Exception:
        pass
    with _load_lock:
        _is_loading = False


def _save_catalogue(
    conn: sqlite3.Connection, enriched: list[dict], person_index: dict[str, list[dict]]
) -> None:
    try:
        conn.execute("BEGIN IMMEDIATE TRANSACTION")
        conn.execute("DELETE FROM projects")
        conn.execute("DELETE FROM person_index")
        for proj in enriched:
            conn.execute(
                "INSERT OR REPLACE INTO projects (project_id, data) VALUES (?, ?)",
                (proj["project_id"], json.dumps(proj)),
            )
        for name, projs in person_index.items():
            conn.execute(
                "INSERT OR REPLACE INTO person_index (name, projects) VALUES (?, ?)",
                (name, json.dumps(projs)),
            )
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('last_refresh', ?)",
            (str(time.time()),),
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('is_loaded', 'true')"
        )
        conn.commit()
    except Exception:
        logger.exception("Failed to save catalogue to database")
        try:
            conn.rollback()
        except Exception:
            pass
        raise


def load_catalogue() -> None:
    if os.getenv("TEST_MODE", "false").strip().lower() == "true":
        logger.info("TEST_MODE is true. Skipping live Fusion catalogue load.")
        return
    threading.Thread(target=_do_load_catalogue, daemon=True).start()


def get_project_by_id(project_id: str) -> dict | None:
    conn = _get_db()
    cur = conn.execute(
        "SELECT data FROM projects WHERE project_id = ?", (str(project_id),)
    )
    row = cur.fetchone()
    if row:
        return json.loads(row[0])
    return None


def _find_person_projects(person_id: str, full_name: str = "") -> list[dict]:
    conn = _get_db()
    for key in [person_id.strip().lower(), full_name.strip().lower()]:
        if not key:
            continue
        cur = conn.execute("SELECT projects FROM person_index WHERE name = ?", (key,))
        row = cur.fetchone()
        if row:
            return json.loads(row[0])
    return []


def _transform_assignments(assigned: list[dict]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for proj in assigned:
        p_num = proj.get("project_number", "")
        project_no: Any
        try:
            project_no = int(p_num)
        except (ValueError, TypeError):
            project_no = p_num
        tasks = []
        for t in proj.get("tasks", []):
            task_id_value = t.get("task_id")
            raw_id = (
                task_id_value
                if task_id_value not in (None, "")
                else t.get("task_number") or "0"
            )
            task_id: int | str
            try:
                task_id = int(raw_id)
            except (ValueError, TypeError):
                task_id = raw_id
            task = {
                "taskId": task_id,
                "taskDetails": t.get("task_name", ""),
            }
            if t.get("task_number") not in (None, ""):
                task["taskNumber"] = t.get("task_number")
            tasks.append(task)
        result.append(
            {
                "workOrder": f"WO-{p_num}",
                "projects": [
                    {
                        "projectId": proj.get("project_id", ""),
                        "projectNo": project_no,
                        "projectName": proj.get("project_name", ""),
                        "tasks": tasks,
                    }
                ],
            }
        )
    return result


def is_catalogue_loaded() -> bool:
    conn = _get_db()
    cur = conn.execute("SELECT value FROM meta WHERE key = 'is_loaded'")
    row = cur.fetchone()
    return bool(row and row[0] == "true")


def list_assignments_for_worker(
    employee_number: str, full_name: str = ""
) -> list[dict[str, Any]] | None:
    if not is_catalogue_loaded():
        logger.warning("Catalogue not loaded")
        return None
    assigned = _find_person_projects(employee_number, full_name)
    if not assigned:
        return []
    return _transform_assignments(assigned)


async def alist_assignments_for_worker(
    employee_number: str, full_name: str = ""
) -> list[dict[str, Any]] | None:
    return await asyncio.to_thread(
        list_assignments_for_worker, employee_number, full_name
    )


def catalogue_age_seconds() -> float | None:
    conn = _get_db()
    cur = conn.execute("SELECT value FROM meta WHERE key = 'last_refresh'")
    row = cur.fetchone()
    if row:
        return time.time() - float(row[0])
    return None


def status() -> dict[str, Any]:
    conn = _get_db()
    is_loaded = is_catalogue_loaded()
    cur = conn.execute("SELECT value FROM meta WHERE key = 'is_loading'")
    row = cur.fetchone()
    is_loading = row and row[0] == "true"
    cur = conn.execute("SELECT COUNT(*) FROM projects")
    total_projects = cur.fetchone()[0]
    cur = conn.execute("SELECT COUNT(*) FROM person_index")
    total_persons = cur.fetchone()[0]
    return {
        "isLoaded": is_loaded,
        "isLoading": is_loading,
        "totalProjects": total_projects,
        "totalPersonsIndexed": total_persons,
        "catalogueAgeSeconds": catalogue_age_seconds(),
        "refreshIntervalSeconds": _REFRESH_INTERVAL,
    }


async def refresh_catalogue() -> None:
    conn = _get_db()
    cur = conn.execute("SELECT value FROM meta WHERE key = 'is_loading'")
    row = cur.fetchone()
    is_loading = row and row[0] == "true"
    if not is_loading:
        load_catalogue()
