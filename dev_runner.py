"""Start the backend and Vite development servers as one supervised process."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Iterable
from pathlib import Path
from types import FrameType
from typing import IO, TypedDict

ROOT = Path(__file__).resolve().parent
CREATE_NEW_PROCESS_GROUP = 0x00000200

_shutdown_requested = False
_shutdown_in_progress = False


class _PopenKwargs(TypedDict):
    cwd: Path
    env: dict[str, str]
    stdout: int
    stderr: int
    text: bool
    encoding: str
    errors: str
    bufsize: int


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


def _signal_process_tree(process: subprocess.Popen[str], force: bool) -> None:
    if os.name == "nt":
        (process.kill if force else process.terminate)()
        return
    killpg = getattr(os, "killpg", None)
    if killpg is None:
        return
    killpg(process.pid, getattr(signal, "SIGKILL", 9) if force else signal.SIGTERM)


def _stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        _signal_process_tree(process, force=False)
    except OSError:
        pass
    try:
        process.wait(timeout=5)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        _signal_process_tree(process, force=True)
    except OSError:
        pass
    process.wait()


def _start(command: list[str], cwd: Path, env: dict[str, str]) -> subprocess.Popen[str]:
    common: _PopenKwargs = {
        "cwd": cwd,
        "env": env,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "bufsize": 1,
    }
    if os.name == "nt":
        return subprocess.Popen(
            command, **common, creationflags=CREATE_NEW_PROCESS_GROUP
        )
    return subprocess.Popen(command, **common, start_new_session=True)


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


def _handle_shutdown_signal(_signum: int, _frame: FrameType | None) -> None:
    global _shutdown_requested
    if _shutdown_in_progress:
        return
    _shutdown_requested = True
    raise KeyboardInterrupt


def _install_signal_handlers() -> dict[int, object]:
    previous: dict[int, object] = {}
    for name in ("SIGINT", "SIGTERM"):
        signum = getattr(signal, name, None)
        if signum is None:
            continue
        try:
            previous[signum] = signal.signal(signum, _handle_shutdown_signal)
        except (OSError, ValueError):
            continue
    return previous


def _restore_signal_handlers(previous: dict[int, object]) -> None:
    for signum, handler in previous.items():
        try:
            signal.signal(signum, handler)  # type: ignore[arg-type]
        except (OSError, ValueError, TypeError):
            continue


def _drain(processes: Iterable[subprocess.Popen[str] | None]) -> None:
    global _shutdown_in_progress
    _shutdown_in_progress = True
    for process in processes:
        if process is not None:
            _stop_process(process)


def main() -> int:
    global _shutdown_requested, _shutdown_in_progress
    _shutdown_requested = False
    _shutdown_in_progress = False

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
    previous_handlers = _install_signal_handlers()
    try:
        print("Starting OTL Timesheet Assistant development services.")
        try:
            backend = _start(backend_command, ROOT, env)
            frontend = _start(frontend_command, ROOT, env)
        except OSError as exc:
            print(
                f"error: could not start a development service: {exc}", file=sys.stderr
            )
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
            return 130
    finally:
        _drain((backend, frontend))
        _restore_signal_handlers(previous_handlers)


if __name__ == "__main__":
    raise SystemExit(main())
