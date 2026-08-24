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

import json
import logging
import os
import sqlite3
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
_REFRESH_INTERVAL = int(os.getenv("CATALOGUE_REFRESH_SECONDS", str(6 * 3600)))  # 6h default

_DB_PATH = Path(__file__).parent.parent.parent / "data" / "catalogue.db"


def _get_db() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    
    # Ensure tables exist
    conn.execute('''CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS projects (project_id TEXT PRIMARY KEY, data JSON)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS person_index (name TEXT PRIMARY KEY, projects JSON)''')
    conn.commit()
    return conn


def _host_url() -> str:
    """Derive the Fusion host from the OTL_BASE_URL env var."""
    from . import otl_client
    url = otl_client.base_url()
    parsed = urllib.parse.urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _ppm_base() -> str:
    return f"{_host_url()}/fscmRestApi/resources/11.13.18.05"


def _client() -> httpx.Client:
    from . import otl_client
    cred = otl_client.service_credential()
    return httpx.Client(
        auth=cred.auth,
        timeout=httpx.Timeout(60.0, connect=15.0),
        headers={"Accept": "application/json", "Accept-Encoding": "gzip"},
    )


# ---------------------------------------------------------------------------
# Fetch from Fusion APIs
# ---------------------------------------------------------------------------
def _fetch_all_projects(client: httpx.Client) -> list[dict]:
    projects = []
    offset = 0
    limit = 100

    while True:
        resp = client.get(
            f"{_ppm_base()}/projects",
            params={
                "fields": "ProjectId,ProjectNumber,ProjectName,ProjectManagerName,ProjectStatus",
                "limit": limit,
                "offset": offset,
            },
        )
        if resp.status_code != 200:
            logger.error("Failed to fetch projects (HTTP %d): %s", resp.status_code, resp.text[:300])
            break

        items = resp.json().get("items", [])
        if not items:
            break

        projects.extend(items)
        logger.info("  Fetched %d projects (offset=%d)…", len(items), offset)

        if len(items) < limit:
            break
        offset += limit

    return projects


def _fetch_project_tasks(client: httpx.Client, project_id: str) -> list[dict]:
    resp = client.get(
        f"{_ppm_base()}/projects/{project_id}/child/Tasks",
        params={"limit": 100},
    )
    if resp.status_code != 200:
        return []
    return resp.json().get("items", [])


def _fetch_project_team_members(client: httpx.Client, project_id: str) -> list[dict]:
    resp = client.get(
        f"{_ppm_base()}/projects/{project_id}/child/ProjectTeamMembers",
        params={"limit": 100},
    )
    if resp.status_code != 200:
        return []
    return resp.json().get("items", [])


def _fetch_all_resource_assignments(client: httpx.Client) -> list[dict]:
    assignments = []
    offset = 0
    limit = 100

    while True:
        resp = client.get(
            f"{_ppm_base()}/projectResourceAssignments",
            params={
                "fields": "ProjectId,ResourceHCMPersonId,ResourceName",
                "limit": limit,
                "offset": offset,
            },
        )
        if resp.status_code != 200:
            logger.error("Failed to fetch resource assignments (HTTP %d)", resp.status_code)
            break

        items = resp.json().get("items", [])
        if not items:
            break

        assignments.extend(items)
        if len(items) < limit:
            break
        offset += limit

    return assignments


def _build_index(projects_data: list[dict], assignments_data: list[dict] | None = None) -> dict[str, list[dict]]:
    index: dict[str, list[dict]] = {}
    if assignments_data is None:
        assignments_data = []

    for proj in projects_data:
        proj_entry = {
            "project_id": str(proj.get("project_id", "")),
            "project_number": str(proj.get("project_number", "")),
            "project_name": proj.get("project_name", ""),
            "status": proj.get("status", ""),
            "manager": proj.get("manager", ""),
            "tasks": proj.get("tasks", []),
        }

        # 1. Team Members
        for member in proj.get("team_members", []):
            person_name = (member.get("PersonName") or "").strip().lower()
            if not person_name:
                continue
            if person_name not in index:
                index[person_name] = []
            index[person_name].append({
                **proj_entry,
                "role": member.get("ProjectRole", "Team Member"),
            })

        # 2. Resource Assignments
        for assign in assignments_data:
            if str(assign.get("ProjectId")) == proj_entry["project_id"]:
                person_name = (assign.get("ResourceName") or "").strip().lower()
                if not person_name:
                    continue
                if person_name not in index:
                    index[person_name] = []
                already = any(p["project_number"] == proj_entry["project_number"] for p in index[person_name])
                if not already:
                    index[person_name].append({
                        **proj_entry,
                        "role": "Resource Assignment",
                    })

        # 3. Manager
        mgr_name = (proj.get("manager") or "").strip().lower()
        if mgr_name:
            if mgr_name not in index:
                index[mgr_name] = []
            already = any(p["project_number"] == proj_entry["project_number"] for p in index[mgr_name])
            if not already:
                index[mgr_name].append({
                    **proj_entry,
                    "role": "Project Manager",
                })

    return index


# ---------------------------------------------------------------------------
# Load / reload
# ---------------------------------------------------------------------------
def _do_load_catalogue() -> None:
    conn = _get_db()
    
    # Check if already loading by another worker
    cur = conn.execute("SELECT value FROM meta WHERE key = 'is_loading'")
    row = cur.fetchone()
    if row and row[0] == 'true':
        logger.warning("Catalogue load already in progress by another worker")
        conn.close()
        return

    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('is_loading', 'true')")
    conn.commit()

    logger.info("Loading Fusion catalogue from live APIs…")
    start = time.time()

    try:
        client = _client()
    except Exception as e:
        logger.error("Cannot create Fusion API client: %s", e)
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('is_loading', 'false')")
        conn.commit()
        conn.close()
        return

    try:
        raw_projects = _fetch_all_projects(client)
        logger.info("Fetched %d projects total.", len(raw_projects))

        import concurrent.futures

        enriched = []
        def fetch_project_details(p):
            p_id = str(p.get("ProjectId", ""))
            p_num = str(p.get("ProjectNumber", ""))
            p_name = p.get("ProjectName", "")
            
            tasks = _fetch_project_tasks(client, p_id)
            members = _fetch_project_team_members(client, p_id)
            
            return {
                "project_id": p_id,
                "project_number": p_num,
                "project_name": p_name,
                "status": p.get("ProjectStatus", ""),
                "manager": p.get("ProjectManagerName", ""),
                "tasks": [
                    {"task_id": str(t.get("TaskId", "")), "task_number": str(t.get("TaskNumber", "")), "task_name": t.get("TaskName", "")}
                    for t in tasks
                ],
                "team_members": members,
            }

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            future_to_proj = {executor.submit(fetch_project_details, p): p for p in raw_projects}
            for i, future in enumerate(concurrent.futures.as_completed(future_to_proj)):
                try:
                    enriched.append(future.result())
                except Exception as exc:
                    logger.error("Project details fetch generated an exception: %s", exc)
                if (i + 1) % 10 == 0:
                    logger.info("  Enriched %d/%d projects…", i + 1, len(raw_projects))

        logger.info("Fetched details for %d projects.", len(enriched))
        
        logger.info("Fetching project resource assignments...")
        assignments = _fetch_all_resource_assignments(client)
        logger.info("Fetched %d resource assignments.", len(assignments))

        logger.info("Building project index...")
        person_index = _build_index(enriched, assignments_data=assignments)
        
        # Save to SQLite
        conn.execute("BEGIN TRANSACTION")
        conn.execute("DELETE FROM projects")
        conn.execute("DELETE FROM person_index")
        
        for proj in enriched:
            conn.execute("INSERT OR REPLACE INTO projects (project_id, data) VALUES (?, ?)", (proj['project_id'], json.dumps(proj)))
            
        for name, projs in person_index.items():
            conn.execute("INSERT OR REPLACE INTO person_index (name, projects) VALUES (?, ?)", (name, json.dumps(projs)))
            
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('last_refresh', ?)", (str(time.time()),))
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('is_loaded', 'true')")
        conn.commit()

        elapsed = time.time() - start
        logger.info(
            "Fusion catalogue ready: %d projects, %d persons indexed (%.1fs)",
            len(enriched),
            len(person_index),
            elapsed,
        )

    except Exception:
        logger.exception("Failed to load Fusion catalogue")
    finally:
        client.close()
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('is_loading', 'false')")
        conn.commit()
        conn.close()


def load_catalogue() -> None:
    """Trigger background load of catalogue so startup isn't blocked."""
    threading.Thread(target=_do_load_catalogue, daemon=True).start()


def get_project_by_id(project_id: str) -> dict | None:
    conn = _get_db()
    cur = conn.execute("SELECT data FROM projects WHERE project_id = ?", (str(project_id),))
    row = cur.fetchone()
    conn.close()
    if row:
        return json.loads(row[0])
    return None


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def _find_person_projects(person_name: str) -> list[dict]:
    key = person_name.strip().lower()
    conn = _get_db()
    
    # Exact match
    cur = conn.execute("SELECT projects FROM person_index WHERE name = ?", (key,))
    row = cur.fetchone()
    if row:
        conn.close()
        return json.loads(row[0])
        
    # Fuzzy match
    cur = conn.execute("SELECT name, projects FROM person_index")
    for row in cur.fetchall():
        indexed_name = row[0]
        if key in indexed_name or indexed_name in key:
            projects = json.loads(row[1])
            conn.close()
            return projects
            
    conn.close()
    return []


def list_assignments_for_worker(employee_number: str, full_name: str = "") -> list[dict[str, Any]]:
    conn = _get_db()
    cur = conn.execute("SELECT value FROM meta WHERE key = 'is_loaded'")
    row = cur.fetchone()
    is_loaded = row and row[0] == 'true'
    
    if not is_loaded:
        cur = conn.execute("SELECT value FROM meta WHERE key = 'is_loading'")
        row = cur.fetchone()
        is_loading = row and row[0] == 'true'
        
        if is_loading:
            logger.info("Catalogue is loading, waiting up to 10 seconds...")
            for _ in range(20):
                cur = conn.execute("SELECT value FROM meta WHERE key = 'is_loaded'")
                row = cur.fetchone()
                if row and row[0] == 'true':
                    is_loaded = True
                    break
                time.sleep(0.5)
        
        if not is_loaded:
            logger.warning("Catalogue not loaded — returning empty assignments")
            conn.close()
            return []

    conn.close()
    assigned = _find_person_projects(full_name)
    if not assigned:
        return []

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
            raw_id = t.get("task_number") or t.get("task_id") or "0"
            task_id: int | str
            try:
                task_id = int(raw_id)
            except (ValueError, TypeError):
                task_id = raw_id
            tasks.append({
                "taskId": task_id,
                "taskDetails": t.get("task_name", ""),
            })

        result.append({
            "workOrder": f"WO-{p_num}",
            "projects": [
                {
                    "projectId": proj.get("project_id", ""),
                    "projectNo": project_no,
                    "projectName": proj.get("project_name", ""),
                    "tasks": tasks,
                }
            ],
        })

    return result


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------
def catalogue_age_seconds() -> float | None:
    conn = _get_db()
    cur = conn.execute("SELECT value FROM meta WHERE key = 'last_refresh'")
    row = cur.fetchone()
    conn.close()
    if row:
        return time.time() - float(row[0])
    return None


def status() -> dict[str, Any]:
    conn = _get_db()
    cur = conn.execute("SELECT value FROM meta WHERE key = 'is_loaded'")
    row = cur.fetchone()
    is_loaded = row and row[0] == 'true'
    
    cur = conn.execute("SELECT value FROM meta WHERE key = 'is_loading'")
    row = cur.fetchone()
    is_loading = row and row[0] == 'true'
    
    cur = conn.execute("SELECT COUNT(*) FROM projects")
    total_projects = cur.fetchone()[0]
    
    cur = conn.execute("SELECT COUNT(*) FROM person_index")
    total_persons = cur.fetchone()[0]
    conn.close()
    
    return {
        "isLoaded": is_loaded,
        "isLoading": is_loading,
        "totalProjects": total_projects,
        "totalPersonsIndexed": total_persons,
        "catalogueAgeSeconds": catalogue_age_seconds(),
        "refreshIntervalSeconds": _REFRESH_INTERVAL,
    }


# ---------------------------------------------------------------------------
# Async refresh
# ---------------------------------------------------------------------------
async def refresh_catalogue() -> None:
    conn = _get_db()
    cur = conn.execute("SELECT value FROM meta WHERE key = 'is_loading'")
    row = cur.fetchone()
    is_loading = row and row[0] == 'true'
    conn.close()
    
    if not is_loading:
        load_catalogue()
