"""DEMO_MODE: canned upstreams so the app is exercisable without Oracle/OCI.

These tests pin the demo boundary: authentication accepts exactly the shared
demo identity, the catalogue serves synthetic assignments, the assistant stream
contains a submittable proposal, and a submission succeeds without any network.
"""

from __future__ import annotations

import asyncio
import json
import threading

import pytest

DEMO_ENTRY = {
    "projectNo": "D-1001",
    "projectName": "Aurora Field Trial",
    "workOrder": "WO-D-1001",
    "taskId": "81001",
    "taskDetails": "Field data collection",
    "hours": 8,
    "date": "2026-11-02",
    "employeeNumber": "DEMO-0001",
    "recordName": "Demo timesheet entry",
    "requestId": "demo-request-0001",
}


@pytest.fixture
def demo_env(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")


@pytest.fixture(autouse=True)
def restore_strict_assignment_cache():
    # _strict_assignment() memoises into module state that other tests compare
    # across the api facade; leave the process exactly as this module found it.
    from backend.api.v1 import timecards
    from backend.services import timecard_entries

    service_old = timecard_entries._STRICT_ASSIGNMENT_CACHE
    facade_old = timecards._STRICT_ASSIGNMENT_CACHE
    yield
    timecard_entries._STRICT_ASSIGNMENT_CACHE = service_old
    timecards._STRICT_ASSIGNMENT_CACHE = facade_old


def test_demo_verifier_accepts_only_the_shared_identity(demo_env):
    from backend.core import auth

    verifier = auth.DemoCredentialVerifier()
    ok = asyncio.run(verifier.verify("demo", "demo"))
    assert ok is not None
    assert ok.employee_id == auth.DEMO_EMPLOYEE_ID
    assert asyncio.run(verifier.verify("demo", "nope")) is None
    assert asyncio.run(verifier.verify("someone-else", "demo")) is None


def test_service_credential_is_canned_in_demo_mode(demo_env):
    from backend.services import otl_client

    cred = otl_client.service_credential()
    assert cred.username == "demo-service"
    assert cred.password == "demo-service"


def test_catalogue_seeds_synthetic_assignments(demo_env, tmp_path, monkeypatch):
    from backend.services import fusion_catalogue

    monkeypatch.setattr(fusion_catalogue, "_DB_PATH", tmp_path / "catalogue.db")
    monkeypatch.setattr(fusion_catalogue, "_thread_local", threading.local())

    fusion_catalogue._seed_demo_catalogue()

    assert fusion_catalogue.is_catalogue_loaded()
    assignments = fusion_catalogue.list_assignments_for_worker("DEMO-0001")
    assert assignments is not None
    names = {p["projectName"] for o in assignments for p in o["projects"]}
    assert names == {"Aurora Field Trial", "Borealis Maintenance"}


def test_demo_assistant_stream_contains_a_submittable_proposal(
    demo_env, tmp_path, monkeypatch
):
    from backend.services import chat, timecard_entries

    chunks: list[str] = []
    done = False
    for frame in chat.stream_sse("system", []):
        payload = frame.removeprefix("data: ").strip()
        obj = json.loads(payload)
        if "delta" in obj:
            chunks.append(obj["delta"])
        if obj.get("done"):
            done = True
    assert done
    text = "".join(chunks)
    entries = timecard_entries._extract_entries(text)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["taskId"] == "81001"
    assert entry["hours"] == 8
    assert entry["projectNo"] == "D-1001"


def test_submission_path_succeeds_without_network(demo_env, tmp_path, monkeypatch):
    monkeypatch.setenv("IDEMPOTENCY_DB_PATH", str(tmp_path / "idempotency.db"))
    from backend.services import otl_client

    entry = dict(DEMO_ENTRY)
    assignments = [
        {
            "workOrder": "WO-D-1001",
            "projects": [
                {
                    "projectId": "900001",
                    "projectNo": "D-1001",
                    "projectName": "Aurora Field Trial",
                    "tasks": [
                        {"taskId": 81001, "taskDetails": "Field data collection"},
                        {"taskId": 81002, "taskDetails": "Data review and QA"},
                    ],
                }
            ],
        }
    ]
    from backend.services import timecard_entries

    valid, error = timecard_entries._validate_timecard_entries([entry], assignments)
    assert valid, error

    results = asyncio.run(
        otl_client.acreate_many(otl_client.service_credential(), [entry])
    )
    assert len(results) == 1
    result = results[0]
    assert result["ok"] is True
    assert str(result["recordNumber"]).startswith("DEMO-")
