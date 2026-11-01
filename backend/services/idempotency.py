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
