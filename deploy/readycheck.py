from __future__ import annotations

import json
import os
import socket
import ssl
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import ParseResult, unquote, urlparse
from urllib.request import Request, urlopen


def _get(url: str, token: str | None = None) -> None:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, headers=headers, method="GET")
    context = (
        ssl._create_unverified_context()
        if os.getenv("READINESS_INSECURE_TLS", "false").lower() == "true"
        else None
    )
    with urlopen(request, timeout=5, context=context) as response:
        if response.status < 200 or response.status >= 300:
            raise RuntimeError(f"readiness endpoint returned HTTP {response.status}")
        payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict) or payload.get("status") not in {
            "ok",
            "connected",
            "ready",
        }:
            raise RuntimeError("readiness endpoint returned an unexpected status")


def _expect_ok(connection: socket.socket) -> None:
    response = connection.recv(1024)
    if not response.startswith(b"+OK"):
        raise RuntimeError("Redis dependency rejected the readiness probe")


def _redis_socket() -> None:
    raw = os.getenv("REDIS_URL", "").strip()
    if not raw:
        raise RuntimeError("REDIS_REQUIRED is true but REDIS_URL is not set")
    parsed = urlparse(raw)
    if (
        parsed.scheme not in {"redis", "rediss"}
        or not parsed.hostname
        or not parsed.port
    ):
        raise RuntimeError("REDIS_URL must include a host and port")
    context = ssl.create_default_context() if parsed.scheme == "rediss" else None
    with socket.create_connection(
        (parsed.hostname, parsed.port), timeout=3
    ) as connection:
        if context:
            with context.wrap_socket(
                connection, server_hostname=parsed.hostname
            ) as secure_connection:
                _redis_command(secure_connection, parsed)
        else:
            _redis_command(connection, parsed)


def _redis_command(connection: socket.socket, parsed: ParseResult) -> None:
    if parsed.password:
        username = unquote(parsed.username or "default")
        password = unquote(parsed.password)
        command = f"*3\r\n$4\r\nAUTH\r\n${len(username)}\r\n{username}\r\n${len(password)}\r\n{password}\r\n"
        connection.sendall(command.encode("utf-8"))
        _expect_ok(connection)
    connection.sendall(b"*1\r\n$4\r\nPING\r\n")
    _expect_ok(connection)


def main() -> int:
    base_url = os.getenv("READINESS_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    liveness_url = os.getenv("READINESS_URL", f"{base_url}/api/health")
    try:
        _get(liveness_url)
        if os.getenv("REDIS_REQUIRED", "false").strip().lower() == "true":
            _redis_socket()
        dependency_url = os.getenv("READINESS_OTL_URL", "").strip()
        require_dependency = (
            os.getenv("READINESS_REQUIRE_OTL", "false").strip().lower() == "true"
        )
        if require_dependency and not dependency_url:
            raise RuntimeError(
                "READINESS_REQUIRE_OTL is true but READINESS_OTL_URL is empty"
            )
        if dependency_url:
            token_path = os.getenv("READINESS_AUTH_TOKEN_FILE", "").strip()
            if not token_path:
                raise RuntimeError(
                    "READINESS_OTL_URL requires READINESS_AUTH_TOKEN_FILE"
                )
            token_file = Path(token_path)
            if not token_file.is_file():
                raise RuntimeError("readiness token file is unavailable")
            token = token_file.read_text(encoding="utf-8").strip()
            if not token:
                raise RuntimeError("readiness token file is empty")
            _get(dependency_url, token)
    except (
        HTTPError,
        URLError,
        TimeoutError,
        OSError,
        RuntimeError,
        ValueError,
    ) as exc:
        print(f"readiness: failed ({type(exc).__name__})", file=sys.stderr)
        return 1
    print("readiness: passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
