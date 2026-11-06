import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from backend.services.idempotency import (
    IdempotencyKeyError,
    IdempotencyStore,
    IdempotencyUnavailable,
    _conflict_result,
    _pending_result,
    get_idempotency_store,
    idempotency_key_for_entry,
    is_retryable_result,
    reset_idempotency_store,
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


class _FrozenClock:
    def __init__(self, start: float) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    frozen = _FrozenClock(1_700_000_000.0)
    monkeypatch.setattr(time, "time", frozen)
    return frozen


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
    assert conflict.result["code"] == "request_id_conflict"

    assert store.complete(
        key,
        first.token or "",
        {
            "index": 0,
            "ok": False,
            "status": 400,
            "error": "Traceback: secret database password",
            "detail": {"token": "internal-secret"},
        },
    )
    replay = store.claim(key, "payload-a")

    assert replay.state == "replay"
    assert replay.result is not None
    assert replay.result["replayed"] is True
    assert replay.result["error"] == "Oracle rejected this timecard entry."
    assert "secret" not in str(replay.result).lower()
    assert "traceback" not in str(replay.result).lower()


def test_definitive_and_ambiguous_outcomes_are_coded_apart(tmp_path):
    pending = sanitize_idempotency_result(_pending_result())
    conflict = sanitize_idempotency_result(_conflict_result())
    unavailable = sanitize_idempotency_result(
        {"ok": False, "status": 503, "code": "idempotency_unavailable"}
    )

    assert pending["code"] == "submission_in_progress"
    assert conflict["code"] == "request_id_conflict"
    assert pending["error"] != conflict["error"]
    assert "still processing" in pending["error"]
    assert "different timecard data" in conflict["error"]
    assert is_retryable_result(pending) is True
    assert is_retryable_result(unavailable) is True
    assert is_retryable_result(conflict) is False
    assert is_retryable_result({"ok": True, "status": 500}) is False


@pytest.mark.parametrize("backend", ["sqlite", "memory"])
def test_ambiguous_server_failure_is_not_memoised_as_definitive(
    clock, tmp_path, backend
):
    store = _store(_store_path(tmp_path, backend, "ambiguous.db"), ttl_seconds=3600)

    key = scoped_idempotency_key("employee-123", "request-ambiguous")
    claim = store.claim(key, "payload")
    assert claim.token is not None
    assert store.complete(
        key, claim.token, {"ok": False, "status": 500, "error": "gateway timeout"}
    )
    assert store.wait_for_result(key)["code"] == "submission_in_progress"

    retry = store.claim(key, "payload")
    assert retry.state == "claimed"
    assert retry.token is not None
    assert retry.token != claim.token

    assert store.complete(key, retry.token, {"ok": True, "id": "record-after-retry"})
    assert store.claim(key, "payload").state == "replay"


@pytest.mark.parametrize("backend", ["sqlite", "memory"])
def test_released_claim_after_ambiguous_failure_accepts_a_corrected_payload(
    clock, tmp_path, backend
):
    store = _store(_store_path(tmp_path, backend, "corrected.db"), ttl_seconds=3600)
    key = scoped_idempotency_key("employee-123", "request-corrected")

    claim = store.claim(key, "payload-a")
    assert claim.token is not None
    store.complete(key, claim.token, {"ok": False, "status": 503})

    corrected = store.claim(key, "payload-b")

    assert corrected.state == "claimed"
    assert corrected.token is not None


def test_unopenable_idempotency_database_never_degrades_to_memory(tmp_path):
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("occupied", encoding="utf-8")

    with pytest.raises(IdempotencyUnavailable):
        IdempotencyStore(blocker / "nested" / "idempotency.db")


def test_unopenable_idempotency_database_propagates_through_the_shared_store(
    monkeypatch, tmp_path
):
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("occupied", encoding="utf-8")
    monkeypatch.setenv("IDEMPOTENCY_DB_PATH", str(blocker / "nested" / "store.db"))
    reset_idempotency_store()
    try:
        with pytest.raises(IdempotencyUnavailable):
            get_idempotency_store()
    finally:
        reset_idempotency_store()


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


def _store_path(tmp_path, backend, name):
    return str(tmp_path / name) if backend == "sqlite" else ":memory:"


def test_lease_is_independent_of_and_shorter_than_ttl(tmp_path):
    store = _store(tmp_path / "idempotency.db", ttl_seconds=86400, lease_seconds=120)

    assert store.ttl_seconds == 86400
    assert store.lease_seconds == 120

    clamped = _store(tmp_path / "clamped.db", ttl_seconds=60, lease_seconds=3600)
    assert clamped.lease_seconds == 60

    floored = _store(tmp_path / "floored.db", ttl_seconds=60, lease_seconds=0)
    assert floored.lease_seconds == pytest.approx(0.01)


def test_default_store_lease_is_the_crash_recovery_window(monkeypatch, tmp_path):
    monkeypatch.setenv("IDEMPOTENCY_DB_PATH", str(tmp_path / "env.db"))
    monkeypatch.setenv("IDEMPOTENCY_TTL_SECONDS", "86400")
    monkeypatch.setenv("IDEMPOTENCY_LEASE_SECONDS", "45")
    reset_idempotency_store()
    try:
        store = get_idempotency_store()
        assert store.lease_seconds == 45
        assert store.ttl_seconds == 86400
    finally:
        reset_idempotency_store()


@pytest.mark.parametrize("backend", ["sqlite", "memory"])
def test_live_lease_rejects_concurrent_duplicate(clock, tmp_path, backend):
    store = _store(
        _store_path(tmp_path, backend, "live.db"),
        ttl_seconds=3600,
        lease_seconds=120,
    )
    key = scoped_idempotency_key("employee-123", "request-live-lease")

    first = store.claim(key, "payload")
    duplicate = store.claim(key, "payload")
    conflicting = store.claim(key, "other-payload")

    assert first.state == "claimed"
    assert first.token is not None
    assert duplicate.state == "pending"
    assert conflicting.state == "conflict"
    assert store.lease_seconds == 120
    assert store.complete(key, first.token, {"ok": True, "id": "record-live"})

    replay = store.claim(key, "payload")
    assert replay.state == "replay"
    assert replay.result is not None
    assert replay.result["id"] == "record-live"


@pytest.mark.parametrize("backend", ["sqlite", "memory"])
def test_expired_lease_is_reclaimed_after_a_crashed_write(clock, tmp_path, backend):
    store = _store(
        _store_path(tmp_path, backend, "stale.db"),
        ttl_seconds=3600,
        lease_seconds=120,
    )
    key = scoped_idempotency_key("employee-123", "request-stale-lease")

    crashed = store.claim(key, "payload")
    assert crashed.state == "claimed"
    assert crashed.token is not None
    assert store.claim(key, "payload").state == "pending"

    clock.advance(121)

    retry = store.claim(key, "payload")
    assert retry.state == "claimed"
    assert retry.token is not None
    assert retry.token != crashed.token
    assert not store.complete(key, crashed.token, {"ok": True, "id": "stale"})
    assert store.complete(key, retry.token, {"ok": True, "id": "record-recovered"})

    replay = store.claim(key, "payload")
    assert replay.state == "replay"
    assert replay.result is not None
    assert replay.result["id"] == "record-recovered"


@pytest.mark.parametrize("backend", ["sqlite", "memory"])
def test_completed_result_outlives_the_lease(clock, tmp_path, backend):
    store = _store(
        _store_path(tmp_path, backend, "durable.db"),
        ttl_seconds=3600,
        lease_seconds=120,
    )
    key = scoped_idempotency_key("employee-123", "request-durable-lease")

    claim = store.claim(key, "payload")
    assert claim.token is not None
    assert store.complete(key, claim.token, {"ok": True, "id": "record-durable"})

    clock.advance(300)

    replay = store.claim(key, "payload")
    assert replay.state == "replay"
    assert replay.result is not None
    assert replay.result["id"] == "record-durable"
    assert replay.result["replayed"] is True


@pytest.mark.parametrize("backend", ["sqlite", "memory"])
def test_expired_lease_never_reopens_a_conflicting_payload(clock, tmp_path, backend):
    store = _store(
        _store_path(tmp_path, backend, "hash-guard.db"),
        ttl_seconds=3600,
        lease_seconds=120,
    )
    key = scoped_idempotency_key("employee-123", "request-hash-guard")

    assert store.claim(key, "payload-a").state == "claimed"

    clock.advance(121)

    conflict = store.claim(key, "payload-b")
    assert conflict.state == "conflict"
    assert conflict.result is not None
    assert conflict.result["status"] == 409
