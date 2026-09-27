"""Session store behaviour with and without the authoritative Redis store."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import jwt
import pytest

from backend.core import auth
from backend.core.token_blocklist import (
    SessionStoreUnavailable,
    StoredSession,
    _TokenBlocklist,
)

REDIS_URL = "redis://session-store.invalid:6379/0"


class _FakePipeline:
    def __init__(self, redis: _FakeRedis) -> None:
        self._redis = redis
        self.calls: list[tuple[str, str, Any]] = []

    def setex(self, key: str, ttl: int, value: str) -> _FakePipeline:
        self.calls.append(("setex", key, (ttl, value)))
        return self

    def delete(self, key: str) -> _FakePipeline:
        self.calls.append(("delete", key, None))
        return self

    async def execute(self) -> None:
        if "pipeline" in self._redis.fail_on:
            raise ConnectionError("redis down")
        for kind, key, payload in self.calls:
            if kind == "setex":
                ttl, value = payload
                self._redis.data[key] = (ttl, value)
            else:
                self._redis.data.pop(key, None)


class _FakeRedis:
    def __init__(self, *fail_on: str) -> None:
        self.data: dict[str, Any] = {}
        self.fail_on = set(fail_on)
        self.closed = False
        self.pipelines: list[_FakePipeline] = []

    async def ping(self) -> bool:
        if "ping" in self.fail_on:
            raise ConnectionError("redis down")
        return True

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        if "set" in self.fail_on:
            raise ConnectionError("redis down")
        self.data[key] = value

    async def get(self, key: str) -> Any:
        if "get" in self.fail_on:
            raise ConnectionError("redis down")
        return self.data.get(key)

    async def exists(self, key: str) -> int:
        if "exists" in self.fail_on:
            raise ConnectionError("redis down")
        return 1 if key in self.data else 0

    def pipeline(self, transaction: bool = True) -> _FakePipeline:
        pipeline = _FakePipeline(self)
        self.pipelines.append(pipeline)
        return pipeline

    async def close(self) -> None:
        self.closed = True


def _session(employee_id: str = "10021", ttl: float = 3600.0) -> StoredSession:
    return StoredSession(
        employee_id=employee_id,
        username=f"emp{employee_id}",
        full_name="Test Employee",
        expires_at=time.time() + ttl,
    )


def _token(jti: str = "session-1", ttl: int = 3600) -> str:
    issued_at = int(time.time())
    return jwt.encode(
        {
            "sub": "10021",
            "username": "emp10021",
            "iss": auth.SESSION_TOKEN_ISSUER,
            "aud": auth.SESSION_TOKEN_AUDIENCE,
            "iat": issued_at,
            "exp": issued_at + ttl,
            "jti": jti,
        },
        auth._jwt_secret(),
        algorithm=auth.JWT_ALGORITHM,
    )


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch):
    previous = _TokenBlocklist._instance
    _TokenBlocklist._instance = None
    instance = _TokenBlocklist()
    instance._local_sessions.clear()
    instance._local_revoked.clear()
    instance._redis = None
    instance._redis_url = None
    instance._last_reconnect = 0.0
    instance._backoff = 1.0
    monkeypatch.delenv("REDIS_URL", raising=False)
    yield instance
    _TokenBlocklist._instance = previous


def _attach(store: _TokenBlocklist, monkeypatch: pytest.MonkeyPatch, *fail: str):
    redis = _FakeRedis(*fail)
    monkeypatch.setenv("REDIS_URL", REDIS_URL)
    store._redis_url = REDIS_URL
    store._redis = redis
    return redis


@pytest.fixture
def memory_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLOW_IN_MEMORY_SESSIONS", "true")


@pytest.fixture
def no_memory_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLOW_IN_MEMORY_SESSIONS", "false")


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (
            {"employee_id": "", "username": "u", "full_name": "f", "expires_at": 1.0},
            ValueError,
        ),
        (
            {"employee_id": 1, "username": "u", "full_name": "f", "expires_at": 1.0},
            ValueError,
        ),
        (
            {"employee_id": "e", "username": "", "full_name": "f", "expires_at": 1.0},
            ValueError,
        ),
        (
            {"employee_id": "e", "username": 2, "full_name": "f", "expires_at": 1.0},
            ValueError,
        ),
        (
            {"employee_id": "e", "username": "u", "full_name": None, "expires_at": 1.0},
            TypeError,
        ),
        ({"employee_id": "e", "username": "u", "full_name": "f"}, TypeError),
        (
            {"employee_id": "e", "username": "u", "full_name": "f", "expires_at": True},
            TypeError,
        ),
        (
            {
                "employee_id": "e",
                "username": "u",
                "full_name": "f",
                "expires_at": "soon",
            },
            TypeError,
        ),
    ],
)
def test_stored_session_rejects_malformed_records(
    payload: dict[str, Any], expected: type[Exception]
) -> None:
    with pytest.raises(expected):
        StoredSession.from_dict(payload)


def test_stored_session_parses_a_valid_record() -> None:
    session = StoredSession.from_dict(
        {
            "employee_id": "10021",
            "username": "emp10021",
            "full_name": "Test Employee",
            "expires_at": 1234,
        }
    )
    assert session == StoredSession("10021", "emp10021", "Test Employee", 1234.0)
    assert isinstance(session.expires_at, float)


@pytest.mark.asyncio
async def test_redis_is_not_used_when_no_url_is_configured(store) -> None:
    assert await store._ensure_redis() is None


@pytest.mark.asyncio
async def test_a_recent_failure_suppresses_reconnection(
    store, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REDIS_URL", REDIS_URL)
    store._redis_url = REDIS_URL
    store._last_reconnect = time.monotonic()
    store._backoff = 60.0
    assert store._get_redis() is None


@pytest.mark.asyncio
async def test_a_failed_connection_marks_the_failure_and_backs_off(
    store, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("no redis module")

    monkeypatch.setenv("REDIS_URL", REDIS_URL)
    monkeypatch.setattr("redis.asyncio.from_url", _boom)
    assert store._get_redis() is None
    assert store._redis is None
    assert store._backoff == 2.0
    assert store._get_redis() is None


@pytest.mark.asyncio
async def test_health_check_failure_drops_the_client(
    store, monkeypatch: pytest.MonkeyPatch
) -> None:
    redis = _attach(store, monkeypatch, "ping")
    assert await store._ensure_redis() is None
    assert redis.closed is True
    assert store._redis is None


@pytest.mark.asyncio
async def test_expired_local_records_are_cleaned(store, memory_fallback) -> None:
    store._local_sessions["gone"] = _session(ttl=-10)
    store._local_revoked["gone"] = time.time() - 10
    store._local_sessions["kept"] = _session()
    await store._clean_local()
    assert list(store._local_sessions) == ["kept"]
    assert store._local_revoked == {}


@pytest.mark.asyncio
async def test_store_session_writes_through_redis(
    store, monkeypatch: pytest.MonkeyPatch
) -> None:
    redis = _attach(store, monkeypatch)
    session = _session()
    await store.store_session("session-1", session, 900)
    assert json.loads(redis.data["session:session-1"]) == {
        "employee_id": "10021",
        "username": "emp10021",
        "full_name": "Test Employee",
        "expires_at": session.expires_at,
    }
    assert "session:session-1" not in store._local_sessions


@pytest.mark.asyncio
async def test_store_session_fails_closed_when_redis_errors(
    store, monkeypatch: pytest.MonkeyPatch, no_memory_fallback
) -> None:
    redis = _attach(store, monkeypatch, "set")
    with pytest.raises(SessionStoreUnavailable, match="authoritative session store"):
        await store.store_session("session-1", _session(), 900)
    assert redis.closed is True
    assert store._local_sessions == {}


@pytest.mark.asyncio
async def test_store_session_falls_back_to_memory(
    store, monkeypatch: pytest.MonkeyPatch, memory_fallback
) -> None:
    _attach(store, monkeypatch, "set")
    await store.store_session("session-1", _session(), 900)
    assert "session-1" in store._local_sessions


@pytest.mark.asyncio
async def test_store_session_fails_closed_without_any_store(
    store, no_memory_fallback
) -> None:
    with pytest.raises(SessionStoreUnavailable, match="no safe fallback"):
        await store.store_session("session-1", _session(), 900)


@pytest.mark.asyncio
async def test_storing_a_session_clears_a_local_denial(store, memory_fallback) -> None:
    store._local_revoked["session-1"] = time.time() + 60
    await store.store_session("session-1", _session(), 900)
    assert "session-1" not in store._local_revoked
    assert "session-1" in store._local_sessions


@pytest.mark.asyncio
async def test_get_session_reads_through_redis(
    store, monkeypatch: pytest.MonkeyPatch
) -> None:
    redis = _attach(store, monkeypatch)
    session = _session()
    redis.data["session:session-1"] = json.dumps(
        {
            "employee_id": session.employee_id,
            "username": session.username,
            "full_name": session.full_name,
            "expires_at": session.expires_at,
        }
    )
    assert await store.get_session("session-1") == session


@pytest.mark.asyncio
async def test_get_session_honours_a_redis_revocation(
    store, monkeypatch: pytest.MonkeyPatch
) -> None:
    redis = _attach(store, monkeypatch)
    redis.data["revoked:session-1"] = (60, "1")
    redis.data["session:session-1"] = json.dumps(
        {
            "employee_id": "10021",
            "username": "emp10021",
            "full_name": "Test Employee",
            "expires_at": time.time() + 60,
        }
    )
    assert await store.get_session("session-1") is None


@pytest.mark.asyncio
async def test_get_session_returns_none_for_a_missing_key(
    store, monkeypatch: pytest.MonkeyPatch
) -> None:
    _attach(store, monkeypatch)
    assert await store.get_session("session-1") is None


@pytest.mark.asyncio
async def test_get_session_rejects_an_expired_record(
    store, monkeypatch: pytest.MonkeyPatch
) -> None:
    redis = _attach(store, monkeypatch)
    redis.data["session:session-1"] = json.dumps(
        {
            "employee_id": "10021",
            "username": "emp10021",
            "full_name": "Test Employee",
            "expires_at": time.time() - 60,
        }
    )
    assert await store.get_session("session-1") is None


@pytest.mark.asyncio
async def test_get_session_recovers_from_a_corrupt_record(
    store, monkeypatch: pytest.MonkeyPatch, memory_fallback
) -> None:
    await store.store_session("session-1", _session(), 900)
    redis = _attach(store, monkeypatch, "get")
    assert await store.get_session("session-1") is not None
    assert redis.closed is True


@pytest.mark.asyncio
async def test_get_session_fails_closed_when_redis_errors(
    store, monkeypatch: pytest.MonkeyPatch, no_memory_fallback
) -> None:
    _attach(store, monkeypatch, "get")
    with pytest.raises(SessionStoreUnavailable, match="authoritative session store"):
        await store.get_session("session-1")


@pytest.mark.asyncio
async def test_get_session_fails_closed_without_any_store(
    store, no_memory_fallback
) -> None:
    with pytest.raises(SessionStoreUnavailable, match="no safe fallback"):
        await store.get_session("session-1")


@pytest.mark.asyncio
async def test_get_session_respects_a_local_denial(store, memory_fallback) -> None:
    await store.store_session("session-1", _session(), 900)
    store._local_revoked["session-1"] = time.time() + 60
    assert await store.get_session("session-1") is None


@pytest.mark.asyncio
async def test_get_session_reads_the_local_store(store, memory_fallback) -> None:
    await store.store_session("session-1", _session(), 900)
    assert await store.get_session("session-1") is not None
    assert await store.get_session("absent") is None


@pytest.mark.asyncio
async def test_revoke_session_uses_a_redis_transaction(
    store, monkeypatch: pytest.MonkeyPatch
) -> None:
    redis = _attach(store, monkeypatch)
    redis.data["session:session-1"] = "{}"
    await store.revoke_session("session-1", 120)
    assert redis.pipelines[0].calls == [
        ("setex", "revoked:session-1", (120, "1")),
        ("delete", "session:session-1", None),
    ]
    assert "session:session-1" not in redis.data
    assert "revoked:session-1" in redis.data
    assert store._local_revoked == {}


@pytest.mark.asyncio
async def test_revoke_session_denial_survives_a_redis_failure(
    store, monkeypatch: pytest.MonkeyPatch, no_memory_fallback
) -> None:
    _attach(store, monkeypatch, "pipeline")
    with pytest.raises(SessionStoreUnavailable, match="authoritative session store"):
        await store.revoke_session("session-1", 120)
    assert await store._is_locally_denied("session-1") is True


@pytest.mark.asyncio
async def test_revoke_session_denial_survives_a_missing_store(
    store, no_memory_fallback
) -> None:
    with pytest.raises(SessionStoreUnavailable, match="no safe fallback"):
        await store.revoke_session("session-1", 120)
    assert await store._is_locally_denied("session-1") is True


@pytest.mark.asyncio
async def test_revoke_session_updates_the_local_store(store, memory_fallback) -> None:
    await store.store_session("session-1", _session(), 900)
    await store.revoke_session("session-1", 120)
    assert store._local_sessions == {}
    assert "session-1" in store._local_revoked
    assert await store.get_session("session-1") is None


@pytest.mark.asyncio
async def test_add_revokes_the_presented_token(store, memory_fallback) -> None:
    await store.add(_token(jti="session-1"))
    assert await store._is_locally_denied("session-1") is True


@pytest.mark.asyncio
async def test_add_ignores_an_undecodable_token(store, memory_fallback) -> None:
    await store.add("not-a-token")
    assert store._local_revoked == {}


@pytest.mark.asyncio
async def test_is_revoked_treats_undecodable_tokens_as_revoked(
    store, memory_fallback
) -> None:
    assert await store.is_revoked("not-a-token") is True


@pytest.mark.asyncio
async def test_is_revoked_consults_a_local_denial(store, memory_fallback) -> None:
    await store.add(_token(jti="session-1"))
    assert await store.is_revoked(_token(jti="session-1")) is True


@pytest.mark.asyncio
async def test_is_revoked_consults_redis(
    store, monkeypatch: pytest.MonkeyPatch
) -> None:
    redis = _attach(store, monkeypatch)
    redis.data["revoked:session-1"] = (60, "1")
    assert await store.is_revoked(_token(jti="session-1")) is True
    redis.data.pop("revoked:session-1")
    assert await store.is_revoked(_token(jti="session-1")) is False


@pytest.mark.asyncio
async def test_is_revoked_fails_closed_when_redis_errors(
    store, monkeypatch: pytest.MonkeyPatch, no_memory_fallback
) -> None:
    _attach(store, monkeypatch, "exists")
    with pytest.raises(SessionStoreUnavailable, match="authoritative session store"):
        await store.is_revoked(_token(jti="session-1"))


@pytest.mark.asyncio
async def test_is_revoked_fails_closed_without_any_store(
    store, no_memory_fallback
) -> None:
    with pytest.raises(SessionStoreUnavailable, match="no safe fallback"):
        await store.is_revoked(_token(jti="session-1"))


@pytest.mark.asyncio
async def test_is_revoked_treats_unknown_local_sessions_as_revoked(
    store, memory_fallback
) -> None:
    await store.store_session("session-1", _session(), 900)
    assert await store.is_revoked(_token(jti="session-1")) is False
    assert await store.is_revoked(_token(jti="other")) is True


@pytest.mark.asyncio
async def test_clear_local_and_close(store, monkeypatch: pytest.MonkeyPatch) -> None:
    redis = _attach(store, monkeypatch)
    await store.store_session("session-1", _session(), 900)
    await store.clear_local()
    assert store._local_sessions == {}
    assert store._local_revoked == {}
    await store.close()
    assert redis.closed is True
    assert store._redis_url is None
    await store.close()


@pytest.mark.asyncio
async def test_close_without_a_client_is_a_no_op(store) -> None:
    await store._close_redis()
    assert store._redis is None


@pytest.mark.asyncio
async def test_deny_locally_uses_a_floor_of_one_second(store) -> None:
    await store._deny_locally("session-1", 0)
    assert await store._is_locally_denied("session-1") is True
    assert asyncio.iscoroutinefunction(store._deny_locally)
