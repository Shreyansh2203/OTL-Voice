"""Pagination and failure handling for the Fusion PPM catalogue client."""

from __future__ import annotations

import json
from typing import Any

import pytest

from backend.services import fusion_catalogue_client as fcc

_INVALID = object()


class _Response:
    def __init__(
        self,
        payload: Any = None,
        status_code: int = 200,
        text: str = "",
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self) -> Any:
        if self._payload is _INVALID:
            raise ValueError("response was not JSON")
        return self._payload


class _Client:
    def __init__(self, *responses: Any) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, params: dict[str, Any] | None = None) -> _Response:
        self.calls.append((url, dict(params or {})))
        if not self._responses:
            raise AssertionError("unexpected extra request")
        nxt = self._responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


def _projects(count: int, start: int = 0) -> list[dict[str, Any]]:
    return [
        {"id": index, "projectName": f"Project {index}"}
        for index in range(start, start + count)
    ]


def test_fetch_result_defaults_to_complete() -> None:
    result = fcc._FetchResult()
    assert result == []
    assert result.complete is True
    assert fcc._FetchResult([{"a": 1}], complete=False) == [{"a": 1}]
    assert fcc._FetchResult([{"a": 1}], complete=False).complete is False


def test_fetch_complete_only_accepts_known_shapes() -> None:
    assert fcc._fetch_complete(fcc._FetchResult()) is True
    assert fcc._fetch_complete(fcc._FetchResult(complete=False)) is False
    assert fcc._fetch_complete([{"a": 1}]) is True
    assert fcc._fetch_complete({"a": 1}) is False
    assert fcc._fetch_complete(None) is False


@pytest.mark.parametrize(
    ("data", "collected", "expected"),
    [
        ({"hasMore": True}, 0, True),
        ({"has_more": "TRUE"}, 5, True),
        ({"hasMore": "false"}, 5, False),
        ({"totalCount": 10}, 9, True),
        ({"totalCount": 10}, 10, False),
        ({"total_count": "4"}, 1, True),
        ({"totalRecords": 3}, 9, False),
        ({"total": 4}, 1, True),
        ({"totalCount": "not-a-number"}, 0, False),
        ({"items": []}, 0, False),
        ({"hasMore": 1}, 0, False),
    ],
)
def test_has_more_reads_every_supported_shape(
    data: dict[str, Any], collected: int, expected: bool
) -> None:
    assert fcc._has_more(data, collected) is expected


def test_host_url_prefers_the_explicit_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FUSION_HOST_URL", "https://fausion.example.test:443/")
    assert fcc._host_url() == "https://fausion.example.test:443"


def test_host_url_derives_the_origin_from_the_otl_base(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FUSION_HOST_URL", raising=False)
    monkeypatch.setenv("OTL_BASE_URL", "https://fausion.example.test/hcm/v1")
    assert fcc._host_url() == "https://fausion.example.test"


def test_ppm_base_uses_the_default_api_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FUSION_PPM_BASE_URL", "")
    monkeypatch.setenv("FUSION_HOST_URL", "https://fausion.example.test")
    monkeypatch.delenv("FUSION_API_VERSION", raising=False)
    assert (
        fcc._ppm_base()
        == "https://fausion.example.test/fscmRestApi/resources/11.13.18.05"
    )


def test_ppm_base_honours_both_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FUSION_PPM_BASE_URL", "https://ppm.example.test/api/")
    monkeypatch.setenv("FUSION_API_VERSION", "13.1.0.0")
    assert fcc._ppm_base() == "https://ppm.example.test/api"


def test_client_uses_the_service_credential_and_bounded_timeouts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def _credential() -> Any:
        return type("Cred", (), {"auth": ("user", "pass")})()

    monkeypatch.setattr("backend.services.otl_client.service_credential", _credential)
    sentinel: Any = object()
    monkeypatch.setattr(
        fcc.httpx,
        "Client",
        lambda **kwargs: captured.update(kwargs) or sentinel,
    )
    assert fcc._client() is sentinel
    assert captured["auth"] == ("user", "pass")
    assert captured["timeout"].read == 60.0
    assert captured["headers"]["Accept"] == "application/json"


def test_fetch_all_projects_returns_a_single_page() -> None:
    client = _Client(_Response({"items": _projects(2)}))
    result = fcc._fetch_all_projects(client)  # type: ignore[arg-type]
    assert len(result) == 2
    assert result.complete is True
    assert client.calls[0][0].endswith("/projects")
    assert client.calls[0][1] == {"limit": 100, "offset": 0}


def test_fetch_all_projects_follows_pagination() -> None:
    client = _Client(
        _Response({"items": _projects(3), "hasMore": True}),
        _Response({"items": _projects(1, start=3), "hasMore": False}),
    )
    result = fcc._fetch_all_projects(client)  # type: ignore[arg-type]
    assert [item["id"] for item in result] == [0, 1, 2, 3]
    assert result.complete is True
    assert client.calls[1][1]["offset"] == 3


def test_fetch_all_projects_marks_an_incomplete_page_as_incomplete() -> None:
    client = _Client(
        _Response({"items": _projects(3), "hasMore": True}),
        _Response({"items": [], "hasMore": True}),
    )
    result = fcc._fetch_all_projects(client)  # type: ignore[arg-type]
    assert len(result) == 3
    assert result.complete is False


@pytest.mark.parametrize(
    "response",
    [
        _Response(_INVALID),
        _Response({"items": "not-a-list"}),
        _Response({}, status_code=500, text="boom"),
        RuntimeError("connection reset"),
    ],
)
def test_fetch_all_projects_marks_every_failure_incomplete(
    response: Any,
) -> None:
    client = _Client(response)
    result = fcc._fetch_all_projects(client)  # type: ignore[arg-type]
    assert result == []
    assert result.complete is False


def test_fetch_child_items_paginates_with_offsets() -> None:
    client = _Client(
        _Response({"items": [{"id": 1}], "hasMore": True}),
        _Response({"items": [{"id": 2}], "hasMore": False}),
    )
    result = fcc._fetch_child_items(client, "https://ppm.example.test/child")  # type: ignore[arg-type]
    assert [item["id"] for item in result] == [1, 2]
    assert result.complete is True
    assert client.calls[0][1] == {"limit": 100}
    assert client.calls[1][1] == {"limit": 100, "offset": 1}


@pytest.mark.parametrize(
    "response",
    [
        _Response(_INVALID),
        _Response({"items": {"nested": True}}),
        _Response({}, status_code=403, text="denied"),
        OSError("dns failure"),
        _Response({"items": [], "totalCount": 4}),
    ],
)
def test_fetch_child_items_marks_every_failure_incomplete(response: Any) -> None:
    client = _Client(response)
    result = fcc._fetch_child_items(client, "https://ppm.example.test/child")  # type: ignore[arg-type]
    assert result.complete is False


def test_child_resource_urls_are_built_per_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FUSION_PPM_BASE_URL", "https://ppm.example.test")
    client = _Client(_Response({"items": []}), _Response({"items": []}))
    tasks = fcc._fetch_project_tasks(client, "P1")  # type: ignore[arg-type]
    members = fcc._fetch_project_team_members(client, "P1")  # type: ignore[arg-type]
    assert tasks.complete is True
    assert members.complete is True
    assert client.calls[0][0] == "https://ppm.example.test/projects/P1/child/Tasks"
    assert (
        client.calls[1][0]
        == "https://ppm.example.test/projects/P1/child/ProjectTeamMembers"
    )


def test_resource_assignments_request_the_projection() -> None:
    client = _Client(_Response({"items": [{"ProjectId": "P1"}]}))
    result = fcc._fetch_all_resource_assignments(client)  # type: ignore[arg-type]
    assert [item["ProjectId"] for item in result] == ["P1"]
    assert result.complete is True
    url, params = client.calls[0]
    assert url.endswith("/projectResourceAssignments")
    assert params["fields"] == "ProjectId,ResourceHCMPersonId,ResourceName"


def test_resource_assignments_paginate_and_report_truncation() -> None:
    client = _Client(
        _Response({"items": [{"ProjectId": "P1"}], "hasMore": True}),
        _Response({"items": [], "hasMore": True}),
    )
    result = fcc._fetch_all_resource_assignments(client)  # type: ignore[arg-type]
    assert len(result) == 1
    assert result.complete is False
    assert client.calls[1][1]["offset"] == 1


@pytest.mark.parametrize(
    "response",
    [
        _Response(_INVALID),
        _Response({"items": 12}),
        _Response({}, status_code=502, text="bad gateway"),
        TimeoutError("upstream timeout"),
    ],
)
def test_resource_assignments_mark_every_failure_incomplete(response: Any) -> None:
    client = _Client(response)
    result = fcc._fetch_all_resource_assignments(client)  # type: ignore[arg-type]
    assert result == []
    assert result.complete is False


def test_catalogue_fetch_error_is_a_runtime_error() -> None:
    assert issubclass(fcc._CatalogueFetchError, RuntimeError)
    with pytest.raises(fcc._CatalogueFetchError):
        raise fcc._CatalogueFetchError("catalogue")
    assert json.dumps({"ok": True})
