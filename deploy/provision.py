#!/usr/bin/env python3
"""Generate the operator-owned production secrets for an OTL-Voice deployment.

Creates (or refreshes) the values that only an operator can create — the
session signing key, the admin API key, and the readiness-token file — and
writes them into a `.env` seeded from `.env.example`. Values already present
that do not look like placeholders are kept. The script never prints a
secret: it says which files were written and which preflight checks still
need an operator value (Fusion URL/credentials, OCI key, OIDC/AUTH_USERS,
Redis URL, trusted proxies, TLS certs).

Usage (from the repository root)::

    python deploy/provision.py              # writes .env + deploy/secrets/readiness_token
    python deploy/provision.py --dry-run    # report what it would do, write nothing
    python deploy/provision.py --help
"""
from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLACEHOLDER_MARKERS = ("replace-with", "generate_a_secure", "your-", "your_", "<your", "example.com")

# Operator values preflight requires that this script cannot invent.
OPERATOR_REQUIRED = (
    "OTL_BASE_URL",
    "OTL_SERVICE_USERNAME",
    "OTL_SERVICE_PASSWORD",
    "OCI_REGION",
    "OCI_COMPARTMENT_ID",
    "REDIS_URL",
    "TRUSTED_PROXY_IPS / TRUSTED_PROXY_CIDRS",
)


def _read_kv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key] = value
    return values


def _is_placeholder(value: str) -> bool:
    lowered = value.strip().lower()
    if not lowered:
        return True
    return any(marker in lowered for marker in PLACEHOLDER_MARKERS)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env-file", default=str(ROOT / ".env"), type=Path)
    parser.add_argument("--example", default=str(ROOT / ".env.example"), type=Path)
    parser.add_argument(
        "--token-file",
        default=str(ROOT / "deploy" / "secrets" / "readiness_token"),
        type=Path,
    )
    parser.add_argument("--dry-run", action="store_true", help="report without writing")
    args = parser.parse_args()

    if not args.example.is_file():
        print(f"provision: example file not found: {args.example}", file=sys.stderr)
        return 1

    example_text = args.example.read_text(encoding="utf-8")
    existing = _read_kv(args.env_file)

    generated: dict[str, str] = {}
    for name in ("SESSION_SECRET_KEY", "ADMIN_API_KEY"):
        if _is_placeholder(existing.get(name, "")):
            generated[name] = secrets.token_urlsafe(48)  # >=32 bytes for SESSION_SECRET_KEY

    # Rebuild .env from the example so every documented variable exists,
    # keeping any real operator values already in place.
    lines: list[str] = []
    for raw_line in example_text.splitlines():
        stripped = raw_line.strip()
        if "=" in stripped and not stripped.startswith("#"):
            key = stripped.split("=", 1)[0].strip()
            if key in generated:
                lines.append(f"{key}={generated[key]}")
            elif key in existing and not _is_placeholder(existing[key]):
                lines.append(f"{key}={existing[key]}")
            else:
                lines.append(raw_line)
        else:
            lines.append(raw_line)
    new_env = "\n".join(lines).rstrip() + "\n"

    if args.dry_run:
        print(f"provision: would write {args.env_file} and {args.token_file}")
        for name in generated:
            print(f"provision: would generate {name} (value not shown)")
        print(f"provision: operator must still supply: {', '.join(OPERATOR_REQUIRED)}")
        print("provision: dry run; nothing written")
        return 0

    args.env_file.write_text(new_env, encoding="utf-8")
    args.token_file.parent.mkdir(parents=True, exist_ok=True)
    args.token_file.write_text(secrets.token_urlsafe(32), encoding="utf-8")

    print(f"provision: wrote {args.env_file} ({len(generated)} secret(s) generated)")
    print(f"provision: wrote {args.token_file} (mode 0400; rotate through the session process)")
    print(f"provision: operator must still supply: {', '.join(OPERATOR_REQUIRED)}")
    print("provision: then place fullchain.pem/privkey.pem in deploy/nginx/certs/ and run:")
    print("provision:   python deploy/preflight.py --env-file .env --mode production")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
