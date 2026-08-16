"""
Fusion Live Catalogue
======================
Fetches projects, tasks, and team-member allocations directly from Oracle
Fusion Cloud REST APIs on startup, caches them in memory, and provides
fast lookups by employee name.

No local JSON files are used — everything is pulled live from Fusion.
The catalogue auto-refreshes on a configurable interval (default: 6 hours).
"""

from __future__ import annotations

import logging
import os
import time
import urllib.parse
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
_REFRESH_INTERVAL = int(os.getenv("CATALOGUE_REFRESH_SECONDS", str(6 * 3600)))  # 6h default


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
# In-memory state
# ---------------------------------------------------------------------------
# Maps lowercase person name -> list of project dicts
_person_index: dict[str, list[dict]] = {}
# All projects fetched
_all_projects: list[dict] = []
_last_refresh: float = 0.0
_is_loaded: bool = False
_is_loading: bool = False


# ---------------------------------------------------------------------------
# Fetch from Fusion APIs
# ---------------------------------------------------------------------------
def _fetch_all_projects(client: httpx.Client) -> list[dict]:
    """Fetch all projects from PPM REST API with pagination."""
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
    """Fetch tasks for a single project."""
    resp = client.get(
        f"{_ppm_base()}/projects/{project_id}/child/Tasks",
        params={"limit": 100},
    )
    if resp.status_code != 200:
        return []
    return resp.json().get("items", [])


def _fetch_project_team_members(client: httpx.Client, project_id: str) -> list[dict]:
    """Fetch team members for a single project."""
    resp = client.get(
        f"{_ppm_base()}/projects/{project_id}/child/ProjectTeamMembers",
        params={"limit": 100},
    )
    if resp.status_code != 200:
        return []
    return resp.json().get("items", [])


def _build_index(projects_data: list[dict]) -> dict[str, list[dict]]:
    """
    Build a person-name → projects index from the fetched data.
    Each person entry contains the projects they are assigned to, with tasks.
    """
    index: dict[str, list[dict]] = {}

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
            person_name = (member.get("PersonName") or "").strip().lower()
            if not person_name:
                continue

            if person_name not in index:
                index[person_name] = []

            index[person_name].append({
                **proj_entry,
                "role": member.get("ProjectRole", "Team Member"),
            })

        # Also index by project manager name
        mgr_name = (proj.get("manager") or "").strip().lower()
        if mgr_name and mgr_name not in index:
            index[mgr_name] = []
        if mgr_name:
            # Check if manager is already in the list for this project
            already = any(
                p["project_number"] == proj_entry["project_number"]
                for p in index.get(mgr_name, [])
            )
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
    """Fetch all projects, tasks, and team members from Fusion and build the index."""
    global _person_index, _all_projects, _last_refresh, _is_loaded, _is_loading

    if _is_loading:
        logger.warning("Catalogue load already in progress")
        return
        
    _is_loading = True
    logger.info("Loading Fusion catalogue from live APIs…")
    start = time.time()

    try:
        client = _client()
    except Exception as e:
        logger.error("Cannot create Fusion API client: %s", e)
        _is_loading = False
        return

    try:
        # 1. Fetch all projects
        raw_projects = _fetch_all_projects(client)
        logger.info("Fetched %d projects total.", len(raw_projects))

        import concurrent.futures

        # 2. For each project, fetch tasks and team members in parallel
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

        # 3. Build the person-name index
        _person_index = _build_index(enriched)
        _all_projects = enriched
        _last_refresh = time.time()
        _is_loaded = True

        elapsed = time.time() - start
        logger.info(
            "Fusion catalogue ready: %d projects, %d persons indexed (%.1fs)",
            len(enriched),
            len(_person_index),
            elapsed,
        )

    except Exception:
        logger.exception("Failed to load Fusion catalogue")
    finally:
        client.close()
        _is_loading = False


def load_catalogue() -> None:
    """Trigger background load of catalogue so startup isn't blocked."""
    import threading
    threading.Thread(target=_do_load_catalogue, daemon=True).start()


def get_project_by_id(project_id: str) -> dict | None:
    """Return a project dictionary from the cache by its ID."""
    for p in _all_projects:
        if str(p.get("project_id")) == str(project_id):
            return p
    return None


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def _find_person_projects(person_name: str) -> list[dict]:
    """Find projects for a person by name (case-insensitive fuzzy match)."""
    key = person_name.strip().lower()
    
    # Exact match first
    if key in _person_index:
        return _person_index[key]
        
    # Fuzzy match: handle discrepancies like "JESSY JESSY.BROWN" vs "JESSY.BROWN"
    for indexed_name, projects in _person_index.items():
        if key in indexed_name or indexed_name in key:
            return projects

    return []


def list_assignments_for_worker(employee_number: str, full_name: str = "") -> list[dict[str, Any]]:
    """
    Return the person's assigned projects in the structure expected by
    ``otl_client.list_worker_assignments``.

    Uses the person's full_name to look up their project assignments from
    the live Fusion catalogue.
    """
    if not _is_loaded:
        if _is_loading:
            logger.info("Catalogue is loading, waiting up to 10 seconds...")
            for _ in range(20):
                if _is_loaded:
                    break
                time.sleep(0.5)
        
        if not _is_loaded:
            logger.warning("Catalogue not loaded — returning empty assignments")
            return []

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
    """How many seconds since the last successful refresh."""
    if _last_refresh == 0:
        return None
    return time.time() - _last_refresh


def status() -> dict[str, Any]:
    """Return current catalogue status."""
    return {
        "isLoaded": _is_loaded,
        "isLoading": _is_loading,
        "totalProjects": len(_all_projects),
        "totalPersonsIndexed": len(_person_index),
        "catalogueAgeSeconds": catalogue_age_seconds(),
        "refreshIntervalSeconds": _REFRESH_INTERVAL,
    }


# ---------------------------------------------------------------------------
# Async refresh
# ---------------------------------------------------------------------------
async def refresh_catalogue() -> None:
    """Re-fetch everything from Fusion APIs (runs in a thread to avoid blocking)."""
    if not _is_loading:
        load_catalogue()
