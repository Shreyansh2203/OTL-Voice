"""Run the frontend Playwright package script from any working directory."""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main(argv: Sequence[str] | None = None) -> int:
    pnpm = shutil.which("pnpm")
    if pnpm is None:
        print("error: 'pnpm' is required to run E2E tests", file=sys.stderr)
        return 127
    frontend = ROOT / "frontend"
    if not (frontend / "package.json").is_file():
        print("error: frontend/package.json is missing", file=sys.stderr)
        return 2

    arguments = list(sys.argv[1:] if argv is None else argv)
    command = [pnpm, "--dir", str(frontend), "run", "test:e2e", *arguments]
    print("==> pnpm --dir frontend run test:e2e", flush=True)
    try:
        result = subprocess.run(command, cwd=ROOT, check=False)
    except OSError as exc:
        print(f"error: could not start {pnpm!r}: {exc}", file=sys.stderr)
        return 127
    return result.returncode if result.returncode >= 0 else 128 - result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
