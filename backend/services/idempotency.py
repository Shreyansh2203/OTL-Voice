from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 24 * 60 * 60
DEFAULT_LEASE_SECONDS = 2 * 60
DEFAULT_WAIT_SECONDS = 35.0
DEFAULT_POLL_SECONDS = 0.05
MIN_INTERVAL_SECONDS = 0.01
MAX_KEY_LENGTH = 128
MAX_RESULT_STRING_LENGTH = 256
_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_RESULT_FIELDS = {
    "index",
    "ok",
    "id",
    "recordNumber",
    "recordName",
    "status",
    "error",
    "code",
    "correlationId",
    "requestId",
    "replayed",
}
RESULT_CODE_SUBMISSION_IN_PROGRESS = "submission_in_progress"
RESULT_CODE_REQUEST_ID_CONFLICT = "request_id_conflict"
RESULT_CODE_CLAIM_LOST = "idempotency_claim_lost"
RESULT_CODE_STORE_UNAVAILABLE = "idempotency_unavailable"
RESULT_CODE_ORACLE_UNAVAILABLE = "oracle_unavailable"
_RESULT_CODES = frozenset(
    {
        RESULT_CODE_SUBMISSION_IN_PROGRESS,
        RESULT_CODE_REQUEST_ID_CONFLICT,
        RESULT_CODE_CLAIM_LOST,
        RESULT_CODE_STORE_UNAVAILABLE,
        RESULT_CODE_ORACLE_UNAVAILABLE,
    }
)
AMBIGUOUS_CODES = frozenset(
    {RESULT_CODE_STORE_UNAVAILABLE, RESULT_CODE_ORACLE_UNAVAILABLE}
)
RETRYABLE_CODES = frozenset(
    {
        RESULT_CODE_SUBMISSION_IN_PROGRESS,
        RESULT_CODE_CLAIM_LOST,
        RESULT_CODE_STORE_UNAVAILABLE,
        RESULT_CODE_ORACLE_UNAVAILABLE,
    }
)
_ERROR_MESSAGES = {
    400: "Oracle rejected this timecard entry.",
    401: "Oracle authentication failed.",
    403: "Oracle authorization failed.",
    404: "The timecard request was not found.",
    409: "The timecard request conflicts with an existing request.",
    422: "Oracle rejected this timecard entry.",
    429: "Oracle is temporarily busy. Please retry later.",
}
_CODE_MESSAGES = {
    RESULT_CODE_SUBMISSION_IN_PROGRESS: (
        "A matching submission is still processing. Retry with the same requestId."
    ),
    RESULT_CODE_REQUEST_ID_CONFLICT: (
        "This requestId was already used for different timecard data."
    ),
    RESULT_CODE_CLAIM_LOST: (
        "The submission could not be recorded as complete. Retry with the same "
        "requestId."
    ),
    RESULT_CODE_STORE_UNAVAILABLE: (
        "The idempotency store is unavailable. Retry with the same requestId."
    ),
    RESULT_CODE_ORACLE_UNAVAILABLE: (
        "Oracle Cloud is temporarily unavailable. Retry with the same requestId."
    ),
}


class IdempotencyKeyError(ValueError):
    pass


class IdempotencyUnavailable(RuntimeError):
    pass


def validate_idempotency_key(value: Any) -> str:
    if not isinstance(value, str):
        raise IdempotencyKeyError("requestId must be a string.")
    if not value or value != value.strip():
        raise IdempotencyKeyError("requestId cannot be empty or contain padding.")
    if len(value) > MAX_KEY_LENGTH or not _KEY_PATTERN.fullmatch(value):
        raise IdempotencyKeyError(
            "requestId must be 1-128 letters, numbers, dots, underscores, colons, or hyphens."
        )
    return value


def idempotency_key_for_entry(
    entry: dict[str, Any], fallback: str | None = None
) -> str | None:
    fields = ("requestId", "idempotencyKey", "Idempotency-Key")
    supplied = [entry[field] for field in fields if field in entry]
    if fallback is not None:
        supplied.append(fallback)
    if not supplied:
        return None
    keys: list[str] = []
    for value in supplied:
        keys.append(validate_idempotency_key(value))
    if any(key != keys[0] for key in keys[1:]):
        raise IdempotencyKeyError("Conflicting requestId values were supplied.")
    return keys[0]


def scoped_idempotency_key(employee_number: str, request_id: str) -> str:
    employee_hash = hashlib.sha256(
        str(employee_number).encode("utf-8"), usedforsecurity=False
    ).hexdigest()[:24]
    return f"timecard:{employee_hash}:{validate_idempotency_key(request_id)}"


def request_fingerprint(entry: dict[str, Any]) -> str:
    payload = {
        key: value
        for key, value in entry.items()
        if key not in {"requestId", "idempotencyKey", "Idempotency-Key"}
        and "employeeName" not in key.casefold()
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded, usedforsecurity=False).hexdigest()


def _safe_string(value: Any) -> str:
    return str(value)[:MAX_RESULT_STRING_LENGTH]


def _result_status(result: dict[str, Any]) -> int:
    try:
        return int(result.get("status", 500))
    except (TypeError, ValueError):
        return 500


def _is_ambiguous_result(result: dict[str, Any]) -> bool:
    """True when the write outcome is unknown, so the result must not be memoised.

    A 5xx from Oracle leaves it unknown whether the row was created, and an
    unavailable idempotency store means nothing was submitted at all. Neither is a
    definitive answer, so neither may become a replayable completed record: the
    claim is released and the caller is told to retry the same ``requestId``.
    """
    if result.get("ok"):
        return False
    if result.get("code") in AMBIGUOUS_CODES:
        return True
    return _result_status(result) >= 500


def is_retryable_result(result: dict[str, Any]) -> bool:
    """True when re-sending the same requestId can change the outcome."""
    if result.get("ok"):
        return False
    code = result.get("code")
    if code in RETRYABLE_CODES:
        return True
    if code == RESULT_CODE_REQUEST_ID_CONFLICT:
        return False
    status = _result_status(result)
    return status >= 500 or status in (409, 429)


def _safe_error(status: Any, code: str | None = None) -> str:
    if code is not None and code in _CODE_MESSAGES:
        return _CODE_MESSAGES[code]
    try:
        status_code = int(status)
    except (TypeError, ValueError):
        status_code = 500
    if status_code in _ERROR_MESSAGES:
        return _ERROR_MESSAGES[status_code]
    if 500 <= status_code <= 599:
        return "Oracle Cloud is temporarily unavailable."
    return "Timecard submission failed."


def sanitize_idempotency_result(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {"ok": False, "status": 500, "error": _safe_error(500)}
    safe: dict[str, Any] = {}
    for field in _RESULT_FIELDS:
        if field not in result:
            continue
        value = result[field]
        if field == "ok" or field == "replayed":
            safe[field] = bool(value)
        elif field == "index":
            try:
                safe[field] = max(0, int(value))
            except (TypeError, ValueError):
                continue
        elif field == "status":
            try:
                status = int(value)
            except (TypeError, ValueError):
                status = 500
            safe[field] = status if 400 <= status <= 599 else 500
        elif field == "code":
            if isinstance(value, str) and value in _RESULT_CODES:
                safe[field] = value
        elif field == "error":
            code = result.get("code")
            safe[field] = _safe_error(
                result.get("status", 500), code if isinstance(code, str) else None
            )
        elif field == "correlationId":
            candidate = _safe_string(value)
            if re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", candidate):
                safe[field] = candidate
        else:
            safe[field] = _safe_string(value)
    safe.setdefault("ok", False)
    if not safe["ok"]:
        code = safe.get("code")
        safe["error"] = _safe_error(
            safe.get("status", 500), code if isinstance(code, str) else None
        )
    return safe


def _pending_result() -> dict[str, Any]:
    return {
        "ok": False,
        "status": 409,
        "code": RESULT_CODE_SUBMISSION_IN_PROGRESS,
        "error": _CODE_MESSAGES[RESULT_CODE_SUBMISSION_IN_PROGRESS],
    }


def _conflict_result() -> dict[str, Any]:
    return {
        "ok": False,
        "status": 409,
        "code": RESULT_CODE_REQUEST_ID_CONFLICT,
        "error": _CODE_MESSAGES[RESULT_CODE_REQUEST_ID_CONFLICT],
    }


@dataclass(frozen=True)
class IdempotencyClaim:
    state: Literal["claimed", "pending", "replay", "conflict"]
    token: str | None = None
    result: dict[str, Any] | None = None


@dataclass
class _MemoryRecord:
    state: str
    request_hash: str
    result_json: str | None
    owner_token: str | None
    lease_until: float
    expires_at: float


class _MemoryBackend:
    def __init__(self) -> None:
        self._records: dict[str, _MemoryRecord] = {}
        self._lock = threading.Lock()

    def claim(
        self, key: str, request_hash: str, ttl: float, lease: float
    ) -> IdempotencyClaim:
        now = time.time()
        with self._lock:
            self._cleanup(now)
            record = self._records.get(key)
            if record is None:
                token = uuid.uuid4().hex
                self._records[key] = _MemoryRecord(
                    state="pending",
                    request_hash=request_hash,
                    result_json=None,
                    owner_token=token,
                    lease_until=now + lease,
                    expires_at=now + ttl,
                )
                return IdempotencyClaim(state="claimed", token=token)
            if record.request_hash != request_hash:
                return IdempotencyClaim(state="conflict", result=_conflict_result())
            if record.state == "complete" and record.result_json:
                result = json.loads(record.result_json)
                result["replayed"] = True
                return IdempotencyClaim(state="replay", result=result)
            if record.lease_until <= now:
                token = uuid.uuid4().hex
                record.state = "pending"
                record.owner_token = token
                record.lease_until = now + lease
                return IdempotencyClaim(state="claimed", token=token)
            return IdempotencyClaim(state="pending")

    def complete(self, key: str, token: str, result: dict[str, Any]) -> bool:
        now = time.time()
        safe = sanitize_idempotency_result(result)
        with self._lock:
            record = self._records.get(key)
            if (
                record is None
                or record.state != "pending"
                or record.owner_token != token
                or record.lease_until <= now
                or record.expires_at <= now
            ):
                return False
            if _is_ambiguous_result(safe):
                del self._records[key]
                return True
            record.state = "complete"
            record.result_json = json.dumps(safe, separators=(",", ":"))
            record.owner_token = None
            record.lease_until = 0
            return True

    def read(self, key: str) -> dict[str, Any] | None:
        now = time.time()
        with self._lock:
            self._cleanup(now)
            record = self._records.get(key)
            if record is None or record.state != "complete" or not record.result_json:
                return None
            result = json.loads(record.result_json)
            result.pop("_owner_token", None)
            result["replayed"] = True
            return sanitize_idempotency_result(result)

    def _cleanup(self, now: float) -> None:
        expired = [
            key for key, record in self._records.items() if record.expires_at <= now
        ]
        for key in expired:
            del self._records[key]


class _SQLiteBackend:
    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS idempotency_records (
                    key TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    result_json TEXT,
                    owner_token TEXT,
                    lease_until REAL NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idempotency_expiry "
                "ON idempotency_records (expires_at)"
            )
            connection.commit()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=30, isolation_level=None)
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def claim(
        self, key: str, request_hash: str, ttl: float, lease: float
    ) -> IdempotencyClaim:
        now = time.time()
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE TRANSACTION")
                connection.execute(
                    "DELETE FROM idempotency_records WHERE expires_at <= ?", (now,)
                )
                row = connection.execute(
                    "SELECT state, request_hash, result_json, lease_until "
                    "FROM idempotency_records WHERE key = ?",
                    (key,),
                ).fetchone()
                if row is None:
                    token = uuid.uuid4().hex
                    connection.execute(
                        "INSERT INTO idempotency_records "
                        "(key, state, request_hash, result_json, owner_token, lease_until, "
                        "created_at, expires_at) VALUES (?, 'pending', ?, NULL, ?, ?, ?, ?)",
                        (key, request_hash, token, now + lease, now, now + ttl),
                    )
                    connection.commit()
                    return IdempotencyClaim(state="claimed", token=token)
                state, stored_hash, result_json, lease_until = row
                if stored_hash != request_hash:
                    connection.commit()
                    return IdempotencyClaim(state="conflict", result=_conflict_result())
                if state == "complete" and result_json:
                    connection.commit()
                    result = json.loads(result_json)
                    result["replayed"] = True
                    return IdempotencyClaim(
                        state="replay", result=sanitize_idempotency_result(result)
                    )
                if float(lease_until) <= now:
                    token = uuid.uuid4().hex
                    reclaimed = connection.execute(
                        "UPDATE idempotency_records SET owner_token = ?, lease_until = ? "
                        "WHERE key = ? AND state = 'pending'",
                        (token, now + lease, key),
                    )
                    connection.commit()
                    if reclaimed.rowcount == 1:
                        return IdempotencyClaim(state="claimed", token=token)
                    return IdempotencyClaim(state="pending")
                connection.commit()
                return IdempotencyClaim(state="pending")
        except sqlite3.Error as exc:
            raise IdempotencyUnavailable("Idempotency store is unavailable.") from exc

    def complete(self, key: str, token: str, result: dict[str, Any]) -> bool:
        safe = sanitize_idempotency_result(result)
        now = time.time()
        if _is_ambiguous_result(safe):
            try:
                with self._connect() as connection:
                    cursor = connection.execute(
                        "DELETE FROM idempotency_records WHERE key = ? "
                        "AND state = 'pending' AND owner_token = ?",
                        (key, token),
                    )
                    return cursor.rowcount == 1
            except sqlite3.Error as exc:
                raise IdempotencyUnavailable(
                    "Idempotency store is unavailable."
                ) from exc
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    "UPDATE idempotency_records SET state = 'complete', result_json = ?, "
                    "owner_token = NULL, lease_until = 0 WHERE key = ? AND state = 'pending' "
                    "AND owner_token = ? AND lease_until > ? AND expires_at > ?",
                    (json.dumps(safe, separators=(",", ":")), key, token, now, now),
                )
                return cursor.rowcount == 1
        except sqlite3.Error as exc:
            raise IdempotencyUnavailable("Idempotency store is unavailable.") from exc

    def read(self, key: str) -> dict[str, Any] | None:
        now = time.time()
        try:
            with self._connect() as connection:
                connection.execute(
                    "DELETE FROM idempotency_records WHERE expires_at <= ?", (now,)
                )
                row = connection.execute(
                    "SELECT state, result_json FROM idempotency_records WHERE key = ?",
                    (key,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise IdempotencyUnavailable("Idempotency store is unavailable.") from exc
        if row is None or row[0] != "complete" or not row[1]:
            return None
        result = json.loads(row[1])
        result["replayed"] = True
        return sanitize_idempotency_result(result)


class IdempotencyStore:
    """Durable write-deduplication store for timecard submissions.

    ``ttl_seconds`` is how long a finished result stays replayable. ``lease_seconds``
    is the independent crash-recovery window for a *claimed but unfinished* write: while
    the lease is live every other caller is refused, and once it expires the claim is
    stale and may be reclaimed. The lease is therefore clamped into ``(0, ttl_seconds]``
    so it can never exceed the lifetime of the record it protects and can never
    resurrect a record that has already expired.

    Only a *definitive* outcome is memoised. When the write outcome is unknown (a 5xx
    from Oracle, or an unavailable store) the claim is released instead of completed, so
    the caller can retry the same ``requestId`` and get a real second attempt rather than
    the identical failure replayed for the full TTL. Losing the durable store is fatal,
    never a silent downgrade to a process-local map: ``IdempotencyUnavailable`` is raised
    so callers fail closed instead of losing every deduplication guarantee.
    """

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        lease_seconds: float = DEFAULT_LEASE_SECONDS,
        wait_seconds: float = DEFAULT_WAIT_SECONDS,
        poll_seconds: float = DEFAULT_POLL_SECONDS,
    ) -> None:
        self.ttl_seconds = max(MIN_INTERVAL_SECONDS, float(ttl_seconds))
        self.lease_seconds = min(
            max(MIN_INTERVAL_SECONDS, float(lease_seconds)), self.ttl_seconds
        )
        self.wait_seconds = max(0.0, float(wait_seconds))
        self.poll_seconds = max(0.001, float(poll_seconds))
        if path is None:
            path = Path(__file__).parent.parent / "data" / "idempotency.db"
        if str(path) == ":memory:":
            self._backend: _MemoryBackend | _SQLiteBackend = _MemoryBackend()
        else:
            try:
                self._backend = _SQLiteBackend(Path(path))
            except (OSError, sqlite3.Error) as exc:
                raise IdempotencyUnavailable(
                    "Durable idempotency database is unavailable."
                ) from exc

    def claim(self, key: str, request_hash: str) -> IdempotencyClaim:
        if not key or len(key) > 512:
            raise ValueError("Invalid idempotency key.")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:._-]{0,511}", key):
            raise ValueError("Invalid idempotency key.")
        return self._backend.claim(
            key, request_hash, self.ttl_seconds, self.lease_seconds
        )

    def complete(self, key: str, token: str, result: dict[str, Any]) -> bool:
        return self._backend.complete(key, token, result)

    def wait_for_result(self, key: str) -> dict[str, Any]:
        deadline = time.monotonic() + self.wait_seconds
        while True:
            result = self._backend.read(key)
            if result is not None:
                return result
            if time.monotonic() >= deadline:
                return _pending_result()
            time.sleep(min(self.poll_seconds, max(0.0, deadline - time.monotonic())))

    def cleanup_expired(self) -> None:
        if isinstance(self._backend, _SQLiteBackend):
            try:
                with self._backend._connect() as connection:
                    connection.execute(
                        "DELETE FROM idempotency_records WHERE expires_at <= ?",
                        (time.time(),),
                    )
            except sqlite3.Error:
                logger.error("Idempotency expiry cleanup failed")


_store: IdempotencyStore | None = None
_store_signature: tuple[str, float, float, float, float] | None = None
_store_lock = threading.Lock()


def _environment_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def get_idempotency_store() -> IdempotencyStore:
    global _store, _store_signature
    default_path = str(Path(__file__).parent.parent / "data" / "idempotency.db")
    path = os.getenv("IDEMPOTENCY_DB_PATH", default_path).strip() or default_path
    signature = (
        path,
        _environment_float("IDEMPOTENCY_TTL_SECONDS", DEFAULT_TTL_SECONDS),
        _environment_float("IDEMPOTENCY_LEASE_SECONDS", DEFAULT_LEASE_SECONDS),
        _environment_float("IDEMPOTENCY_WAIT_SECONDS", DEFAULT_WAIT_SECONDS),
        _environment_float("IDEMPOTENCY_POLL_SECONDS", DEFAULT_POLL_SECONDS),
    )
    if _store is None or _store_signature != signature:
        with _store_lock:
            if _store is None or _store_signature != signature:
                _store = IdempotencyStore(
                    path,
                    ttl_seconds=signature[1],
                    lease_seconds=signature[2],
                    wait_seconds=signature[3],
                    poll_seconds=signature[4],
                )
                _store_signature = signature
    return _store


def reset_idempotency_store() -> None:
    global _store, _store_signature
    with _store_lock:
        _store = None
        _store_signature = None
