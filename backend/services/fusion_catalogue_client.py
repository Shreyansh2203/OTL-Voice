from __future__ import annotations

import logging
import os
import urllib.parse
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class _FetchResult(list[dict[str, Any]]):
    def __init__(
        self, items: list[dict[str, Any]] | None = None, complete: bool = True
    ) -> None:
        super().__init__(items or [])
        self.complete = complete


class _CatalogueFetchError(RuntimeError):
    pass


def _fetch_complete(value: Any) -> bool:
    if isinstance(value, _FetchResult):
        return value.complete
    return isinstance(value, list)


def _has_more(data: dict[str, Any], collected: int = 0) -> bool:
    value = data.get("hasMore", data.get("has_more"))
    if value is True or str(value).strip().lower() == "true":
        return True
    for key in ("totalCount", "total_count", "totalRecords", "total"):
        expected = data.get(key)
        if expected is None:
            continue
        try:
            return int(expected) > collected
        except (TypeError, ValueError):
            continue
    return False


def _host_url() -> str:
    override = os.getenv("FUSION_HOST_URL", "").strip()
    if override:
        return override.rstrip("/")
    from . import otl_client

    url = otl_client.base_url()
    parsed = urllib.parse.urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _ppm_base() -> str:
    override = os.getenv("FUSION_PPM_BASE_URL", "").strip()
    if override:
        return override.rstrip("/")
    api_version = os.getenv("FUSION_API_VERSION", "11.13.18.05")
    return f"{_host_url()}/fscmRestApi/resources/{api_version}"


def _client() -> httpx.Client:
    from . import otl_client

    cred = otl_client.service_credential()
    return httpx.Client(
        auth=cred.auth,
        timeout=httpx.Timeout(60.0, connect=15.0),
        headers={"Accept": "application/json", "Accept-Encoding": "gzip"},
    )


def _fetch_all_projects(client: httpx.Client) -> _FetchResult:
    projects = _FetchResult()
    offset = 0
    limit = 100
    while True:
        try:
            resp = client.get(
                f"{_ppm_base()}/projects",
                params={
                    "limit": limit,
                    "offset": offset,
                },
            )
        except Exception as exc:
            logger.error("Failed to fetch projects: %s", exc)
            projects.complete = False
            return projects
        if resp.status_code != 200:
            logger.error(
                "Failed to fetch projects (HTTP %d): %s",
                resp.status_code,
                resp.text[:300],
            )
            projects.complete = False
            return projects
        try:
            data = resp.json()
            items = data.get("items", [])
        except Exception as exc:
            logger.error("Failed to decode projects response: %s", exc)
            projects.complete = False
            return projects
        if not isinstance(items, list):
            logger.error("Projects response has no items list")
            projects.complete = False
            return projects
        has_more = _has_more(data, len(projects))
        if not items:
            if has_more:
                projects.complete = False
            return projects
        projects.extend(items)
        logger.info("  Fetched %d projects (offset=%d)", len(items), offset)
        if len(items) < limit and not has_more:
            return projects
        offset += len(items)


def _fetch_child_items(client: httpx.Client, url: str) -> _FetchResult:
    items_result = _FetchResult()
    offset = 0
    limit = 100
    while True:
        try:
            params = {"limit": limit}
            if offset:
                params["offset"] = offset
            resp = client.get(url, params=params)
        except Exception as exc:
            logger.error("Failed to fetch child resource %s: %s", url, exc)
            items_result.complete = False
            return items_result
        if resp.status_code != 200:
            items_result.complete = False
            return items_result
        try:
            data = resp.json()
            items = data.get("items", [])
        except Exception as exc:
            logger.error("Failed to decode child resource %s: %s", url, exc)
            items_result.complete = False
            return items_result
        if not isinstance(items, list):
            items_result.complete = False
            return items_result
        has_more = _has_more(data, len(items_result))
        if not items:
            if has_more:
                items_result.complete = False
            return items_result
        items_result.extend(items)
        if not has_more:
            return items_result
        offset += len(items)


def _fetch_project_tasks(client: httpx.Client, project_id: str) -> _FetchResult:
    return _fetch_child_items(
        client, f"{_ppm_base()}/projects/{project_id}/child/Tasks"
    )


def _fetch_project_team_members(client: httpx.Client, project_id: str) -> _FetchResult:
    return _fetch_child_items(
        client,
        f"{_ppm_base()}/projects/{project_id}/child/ProjectTeamMembers",
    )


def _fetch_all_resource_assignments(client: httpx.Client) -> _FetchResult:
    assignments = _FetchResult()
    offset = 0
    limit = 100
    while True:
        try:
            resp = client.get(
                f"{_ppm_base()}/projectResourceAssignments",
                params={
                    "fields": "ProjectId,ResourceHCMPersonId,ResourceName",
                    "limit": limit,
                    "offset": offset,
                },
            )
        except Exception as exc:
            logger.error("Failed to fetch resource assignments: %s", exc)
            assignments.complete = False
            return assignments
        if resp.status_code != 200:
            logger.error(
                "Failed to fetch resource assignments (HTTP %d)", resp.status_code
            )
            assignments.complete = False
            return assignments
        try:
            data = resp.json()
            items = data.get("items", [])
        except Exception as exc:
            logger.error("Failed to decode resource assignments: %s", exc)
            assignments.complete = False
            return assignments
        if not isinstance(items, list):
            logger.error("Resource assignments response has no items list")
            assignments.complete = False
            return assignments
        has_more = _has_more(data, len(assignments))
        if not items:
            if has_more:
                assignments.complete = False
            return assignments
        assignments.extend(items)
        if len(items) < limit and not has_more:
            return assignments
        offset += len(items)
