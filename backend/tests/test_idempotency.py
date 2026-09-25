import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from backend.services.idempotency import (
    IdempotencyKeyError,
    IdempotencyStore,
    idempotency_key_for_entry,
    sanitize_idempotency_result,
    scoped_idempotency_key,
    validate_idempotency_key,
)


def _store(path, **kwargs):
    return IdempotencyStore(
        path,
        ttl_seconds=kwargs.pop("ttl_seconds", 30),
        lease_seconds=kwargs.pop("lease_seconds", 30),
        wait_seconds=kwargs.pop("wait_seconds", 1),
        poll_seconds=kwargs.pop("poll_seconds", 0.005),
    )


def test_request_id_validation_and_aliases(tmp_path):
    assert validate_idempotency_key("request-123") == "request-123"
    assert idempotency_key_for_entry({"requestId": "request-123"}) == "request-123"
    assert (
        idempotency_key_for_entry({"idempotencyKey": "request-123"}, "request-123")
        == "request-123"
    )
    for value in ("", " request-123", "request 123", "request/123", "x" * 129, 123):
        with pytest.raises(IdempotencyKeyError):
            validate_idempotency_key(value)
    with pytest.raises(IdempotencyKeyError, match="Conflicting"):
        idempotency_key_for_entry(
            {"requestId": "request-123", "idempotencyKey": "request-456"}
        )


def test_scoped_key_does_not_store_employee_identifier(tmp_path):
    scoped = scoped_idempotency_key("employee-123", "request-123")

    assert "employee-123" not in scoped
    assert scoped.endswith(":request-123")


def test_atomic_claim_replay_and_payload_conflict(tmp_path):
    store = _store(tmp_path / "idempotency.db")
    key = scoped_idempotency_key("employee-123", "request-123")

    first = store.claim(key, "payload-a")
    duplicate = store.claim(key, "payload-a")
    conflict = store.claim(key, "payload-b")

    assert first.state == "claimed"
    assert first.token is not None
    assert duplicate.state == "pending"
    assert conflict.state == "conflict"
    assert conflict.result is not None
    assert conflict.result["status"] == 409

    assert store.complete(
        key,
        first.token or "",
        {
            "index": 0,
            "ok": False,
            "status": 500,
            "error": "Traceback: secret database password",
            "detail": {"token": "internal-secret"},
        },
    )
    replay = store.claim(key, "payload-a")

    assert replay.state == "replay"
    assert replay.result is not None
    assert replay.result["replayed"] is True
    assert replay.result["error"] == "Oracle Cloud is temporarily unavailable."
    assert "secret" not in str(replay.result).lower()
    assert "traceback" not in str(replay.result).lower()


def test_claim_is_atomic_across_threads(tmp_path):
    store = _store(tmp_path / "idempotency.db")
    key = scoped_idempotency_key("employee-123", "request-concurrent")

    with ThreadPoolExecutor(max_workers=8) as executor:
        claims = list(executor.map(lambda _: store.claim(key, "payload"), range(8)))

    assert sum(claim.state == "claimed" for claim in claims) == 1
    assert sum(claim.state == "pending" for claim in claims) == 7


def test_result_survives_store_reopen_and_expires(tmp_path):
    path = tmp_path / "idempotency.db"
    key = scoped_idempotency_key("employee-123", "request-durable")
    first_store = _store(path)
    claim = first_store.claim(key, "payload")
    assert claim.token is not None
    assert first_store.complete(
        key, claim.token, {"index": 0, "ok": True, "id": "record-1"}
    )

    reopened = _store(path)
    replay = reopened.claim(key, "payload")
    assert replay.state == "replay"
    assert replay.result is not None
    assert replay.result["id"] == "record-1"

    expiring = _store(
        tmp_path / "expiring.db",
        ttl_seconds=0.2,
        lease_seconds=0.2,
        wait_seconds=0.1,
        poll_seconds=0.002,
    )
    expiring_key = scoped_idempotency_key("employee-123", "request-expired")
    expiring_claim = expiring.claim(expiring_key, "payload")
    assert expiring_claim.token is not None
    assert expiring.complete(
        expiring_key, expiring_claim.token, {"ok": True, "id": "record-2"}
    )
    time.sleep(0.25)

    assert expiring.claim(expiring_key, "payload").state == "claimed"


def test_sanitizer_only_returns_public_fields():
    result = sanitize_idempotency_result(
        {
            "index": 0,
            "ok": False,
            "status": 400,
            "error": "ORA-00933: internal SQL at /opt/app.py",
            "detail": {"password": "do-not-store"},
            "requestId": "request-123",
        }
    )

    assert result == {
        "index": 0,
        "ok": False,
        "status": 400,
        "error": "Oracle rejected this timecard entry.",
        "requestId": "request-123",
    }
