from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse


PLACEHOLDER_MARKERS = (
    "replace-with",
    "generate_a_secure",
    "your_secure",
    "your-",
    "change-me",
    "changeme",
    "example.com",
    "<your",
)

BASE_REQUIRED = (
    "SESSION_SECRET_KEY",
    "ADMIN_API_KEY",
    "OTL_BASE_URL",
    "OTL_SERVICE_USERNAME",
    "OTL_SERVICE_PASSWORD",
    "OCI_REGION",
    "OCI_COMPARTMENT_ID",
)

OIDC_REQUIRED = ("OIDC_ISSUER", "OIDC_AUDIENCE")
PLACEHOLDER_RE = re.compile(
    r"^(?:change|replace|your|example|test|dummy|ci-only)|<[^>]+>", re.IGNORECASE
)


def _read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if path.is_file():
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].lstrip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                value = value[1:-1]
            values[key] = value
    values.update(
        {key: value for key, value in os.environ.items() if key not in values}
    )
    return values


def _has_value(values: dict[str, str], name: str) -> bool:
    value = values.get(name, "").strip()
    if not value:
        return False
    normalized = value.lower()
    return not any(
        marker in normalized for marker in PLACEHOLDER_MARKERS
    ) and not PLACEHOLDER_RE.search(normalized)


def _valid_https_url(values: dict[str, str], name: str) -> bool:
    value = values.get(name, "").strip()
    if not _has_value(values, name):
        return False
    parsed = urlparse(value)
    return (
        parsed.scheme == "https"
        and bool(parsed.netloc)
        and not parsed.username
        and not parsed.password
    )


def _valid_redis_url(values: dict[str, str]) -> bool:
    value = values.get("REDIS_URL", "").strip()
    if not _has_value(values, "REDIS_URL"):
        return False
    parsed = urlparse(value)
    return (
        parsed.scheme in {"redis", "rediss"}
        and bool(parsed.hostname)
        and bool(parsed.port)
    )


def _valid_auth_users(value: str) -> bool:
    try:
        document = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return False
    if not isinstance(document, dict) or not document:
        return False
    for key, user in document.items():
        if not isinstance(key, str) or not key.strip():
            return False
        password = (
            user
            if isinstance(user, str)
            else user.get("password")
            if isinstance(user, dict)
            else ""
        )
        if not isinstance(password, str) or not password.startswith("scrypt$"):
            return False
    return True


def _check(values: dict[str, str], mode: str) -> list[str]:
    errors: list[str] = []
    for name in BASE_REQUIRED:
        if not _has_value(values, name):
            errors.append(f"missing or placeholder: {name}")

    oidc_values = tuple(
        _has_value(values, name)
        for name in ("OIDC_ISSUER", "OIDC_AUDIENCE", "OIDC_JWKS_URL")
    )
    oidc_configured = any(oidc_values)
    users_configured = _has_value(values, "AUTH_USERS")
    if oidc_configured and users_configured:
        errors.append("configure either OIDC or AUTH_USERS, not both")
    if oidc_configured:
        if _has_value(values, "OIDC_JWKS_URL"):
            if not _has_value(values, "OIDC_AUDIENCE"):
                errors.append("missing or placeholder: OIDC_AUDIENCE")
            if not _valid_https_url(values, "OIDC_JWKS_URL"):
                errors.append("OIDC_JWKS_URL must be an https URL")
            if _has_value(values, "OIDC_ISSUER") and not _valid_https_url(
                values, "OIDC_ISSUER"
            ):
                errors.append("OIDC_ISSUER must be an https URL")
        else:
            for name in OIDC_REQUIRED:
                if not _has_value(values, name):
                    errors.append(f"missing or placeholder: {name}")
            if not _valid_https_url(values, "OIDC_ISSUER"):
                errors.append("OIDC_ISSUER must be an https URL")
    elif users_configured:
        if not _valid_auth_users(values.get("AUTH_USERS", "")):
            errors.append("AUTH_USERS must be a non-empty JSON scrypt user mapping")
    else:
        errors.append("configure OIDC_ISSUER/OIDC_AUDIENCE or AUTH_USERS")

    if _has_value(values, "AUTH_PASSWORD") and mode == "production":
        errors.append("AUTH_PASSWORD is not allowed in production")

    if not _valid_https_url(values, "OTL_BASE_URL"):
        errors.append("OTL_BASE_URL must be an https URL")
    if not _valid_redis_url(values):
        errors.append("REDIS_URL must be a redis:// or rediss:// URL")
    elif mode == "production" and not values.get("REDIS_URL", "").lower().startswith(
        "rediss://"
    ):
        errors.append("REDIS_URL must use rediss:// in production")
    if not any(
        _has_value(values, name)
        for name in ("OCI_PRIVATE_KEY", "OCI_PRIVATE_KEY_PATH", "OCI_CONFIG_FILE")
    ):
        errors.append("configure an injected OCI private key or OCI config file")

    if (
        mode == "production"
        and _has_value(values, "SESSION_SECRET_KEY")
        and len(values.get("SESSION_SECRET_KEY", "").encode("utf-8")) < 32
    ):
        errors.append("SESSION_SECRET_KEY must contain at least 32 bytes")
    if (
        values.get("SESSION_COOKIE_SECURE", "true").strip().lower() != "true"
        and mode == "production"
    ):
        errors.append("SESSION_COOKIE_SECURE must be true")
    if values.get("SESSION_COOKIE_SAMESITE", "strict").strip().lower() not in {
        "lax",
        "strict",
        "none",
    }:
        errors.append("SESSION_COOKIE_SAMESITE must be lax, strict, or none")
    if (
        values.get("SESSION_COOKIE_SAMESITE", "strict").strip().lower() == "none"
        and values.get("SESSION_COOKIE_SECURE", "true").strip().lower() != "true"
    ):
        errors.append(
            "SESSION_COOKIE_SAMESITE=none requires SESSION_COOKIE_SECURE=true"
        )
    if mode == "production":
        if values.get("REDIS_REQUIRED", "false").strip().lower() != "true":
            errors.append("REDIS_REQUIRED must be true for production")
        if values.get("ALLOW_IN_MEMORY_SESSIONS", "false").strip().lower() == "true":
            errors.append("ALLOW_IN_MEMORY_SESSIONS must be false for production")
        if not any(
            values.get(name, "").strip()
            for name in ("TRUSTED_PROXY_IPS", "TRUSTED_PROXY_CIDRS")
        ):
            errors.append("configure TRUSTED_PROXY_IPS or TRUSTED_PROXY_CIDRS")
    origins = [
        origin.strip()
        for origin in values.get("CORS_ORIGINS", "").split(",")
        if origin.strip()
    ]
    if any(
        "example.com" in origin.lower()
        or "your-" in origin.lower()
        or "replace-with" in origin.lower()
        or urlparse(origin).scheme != "https"
        or not urlparse(origin).netloc
        for origin in origins
    ):
        errors.append(
            "CORS_ORIGINS entries must be absolute non-placeholder https URLs"
        )
    if "*" in origins:
        errors.append("CORS_ORIGINS cannot contain * with credentialed cookies")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate deployment configuration without displaying values"
    )
    parser.add_argument("--env-file", default=".env", type=Path)
    parser.add_argument(
        "--mode", choices=("development", "production", "ci"), default="production"
    )
    args = parser.parse_args()
    values = _read_env(args.env_file)
    if args.mode == "ci":
        required = (
            "SESSION_SECRET_KEY",
            "OTL_BASE_URL",
            "OTL_SERVICE_USERNAME",
            "OTL_SERVICE_PASSWORD",
        )
        errors = [
            f"missing or placeholder: {name}"
            for name in required
            if not _has_value(values, name)
        ]
        if values.get("OTL_BASE_URL", "").strip() and not _valid_https_url(
            values, "OTL_BASE_URL"
        ):
            errors.append("OTL_BASE_URL must be an https URL")
    elif args.mode == "development":
        errors = [] if args.env_file.is_file() else ["missing environment file"]
    else:
        errors = _check(values, args.mode)
    if errors:
        for error in errors:
            print(f"preflight: {error}", file=sys.stderr)
        print(
            f"preflight: failed ({len(errors)} issue(s)); values were not displayed",
            file=sys.stderr,
        )
        return 1
    print(f"preflight: {args.mode} configuration passed; values were not displayed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
