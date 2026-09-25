"""Run the repository's backend and frontend unit-test package scripts."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _required_command(name: str) -> str | None:
    command = shutil.which(name)
    if command is None:
        print(f"error: {name!r} is required to run the test suite", file=sys.stderr)
    return command


def _run_package_script(pnpm: str, script: str) -> int:
    print(f"==> pnpm run {script}", flush=True)
    try:
        result = subprocess.run(
            [pnpm, "run", script],
            cwd=ROOT,
            check=False,
        )
    except OSError as exc:
        print(f"error: could not start {pnpm!r}: {exc}", file=sys.stderr)
        return 127
    return result.returncode if result.returncode >= 0 else 128 - result.returncode


def main() -> int:
    uv = _required_command("uv")
    pnpm = _required_command("pnpm")
    if uv is None or pnpm is None:
        return 127
    if not (ROOT / "frontend" / "package.json").is_file():
        print("error: frontend/package.json is missing", file=sys.stderr)
        return 2

    for script in ("test:backend", "test:frontend"):
        return_code = _run_package_script(pnpm, script)
        if return_code != 0:
            return return_code
    print("All unit-test package scripts passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
