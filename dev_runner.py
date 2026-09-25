"""Start the backend and Vite development servers as one supervised process."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import IO

ROOT = Path(__file__).resolve().parent
CREATE_NEW_PROCESS_GROUP = 0x00000200


def _required_command(name: str) -> str | None:
    command = shutil.which(name)
    if command is None:
        print(f"error: {name!r} is required for local development", file=sys.stderr)
    return command


def _secret_values(env: dict[str, str]) -> tuple[str, ...]:
    markers = ("SECRET", "PASSWORD", "TOKEN", "PRIVATE_KEY", "API_KEY")
    return tuple(
        value
        for key, value in env.items()
        if value and any(marker in key.upper() for marker in markers)
    )


def _stream_output(
    stream: IO[str] | None, prefix: str, color: str, secrets: tuple[str, ...]
) -> None:
    if stream is None:
        return
    for line in iter(stream.readline, ""):
        if not line:
            break
        for secret in secrets:
            line = line.replace(secret, "[REDACTED]")
        reset = "\033[0m" if color else ""
        print(f"{color}{prefix}{reset} {line.rstrip()}", flush=True)


def _stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            process.terminate()
        else:
            os.killpg(process.pid, signal.SIGTERM)
    except OSError:
        pass
    try:
        process.wait(timeout=5)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        if os.name == "nt":
            process.kill()
        else:
            os.killpg(process.pid, signal.SIGKILL)
    except OSError:
        pass
    process.wait()


def _start(command: list[str], cwd: Path, env: dict[str, str]) -> subprocess.Popen[str]:
    options: dict[str, object] = {}
    if os.name == "nt":
        options["creationflags"] = CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    return subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        **options,
    )


def _wait_for_exit(
    backend: subprocess.Popen[str], frontend: subprocess.Popen[str]
) -> int:
    while backend.poll() is None and frontend.poll() is None:
        time.sleep(0.2)
    if backend.poll() is not None:
        return_code = backend.returncode
        _stop_process(frontend)
    else:
        return_code = frontend.returncode
        _stop_process(backend)
    if return_code is None or return_code == 0:
        return 1
    return return_code if return_code > 0 else 128 - return_code


def main() -> int:
    if not (ROOT / ".env").is_file():
        print(
            "error: .env is missing; create it from .env.example before starting "
            "local development",
            file=sys.stderr,
        )
        return 2

    uv = _required_command("uv")
    pnpm = _required_command("pnpm")
    if uv is None or pnpm is None:
        return 127

    env = os.environ.copy()
    env.setdefault("UV_PROJECT_ENVIRONMENT", str(ROOT / ".venv2"))
    backend_command = [
        uv,
        "run",
        "--frozen",
        "uvicorn",
        "backend.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
        "--reload",
        "--reload-include",
        ".env",
    ]
    frontend_command = [pnpm, "--dir", str(ROOT / "frontend"), "run", "dev"]

    backend: subprocess.Popen[str] | None = None
    frontend: subprocess.Popen[str] | None = None
    try:
        print("Starting OTL Timesheet Assistant development services.")
        backend = _start(backend_command, ROOT, env)
        frontend = _start(frontend_command, ROOT, env)
    except OSError as exc:
        print(f"error: could not start a development service: {exc}", file=sys.stderr)
        if backend is not None:
            _stop_process(backend)
        if frontend is not None:
            _stop_process(frontend)
        return 127

    use_color = sys.stdout.isatty()
    secrets = _secret_values(env)
    for process, prefix, color in (
        (backend, "[BACKEND] ", "\033[94m" if use_color else ""),
        (frontend, "[FRONTEND]", "\033[92m" if use_color else ""),
    ):
        threading.Thread(
            target=_stream_output,
            args=(process.stdout, prefix, color, secrets),
            daemon=True,
        ).start()

    try:
        return _wait_for_exit(backend, frontend)
    except KeyboardInterrupt:
        print("\nStopping development services.")
        _stop_process(backend)
        _stop_process(frontend)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
