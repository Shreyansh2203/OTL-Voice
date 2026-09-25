from __future__ import annotations

import os
from ipaddress import IPv4Network, IPv6Network, ip_network

_DEVELOPMENT_ORIGINS = (
    "http://localhost:5173",
    "http://localhost:4173",
    "http://localhost:8000",
    "http://localhost",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:4173",
    "http://127.0.0.1:8000",
    "http://127.0.0.1",
    "capacitor://localhost",
    "https://localhost",
)


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def is_dev_mode() -> bool:
    return env_flag("DEV_MODE")


def is_test_mode() -> bool:
    return env_flag("TEST_MODE")


def is_development_or_test() -> bool:
    return is_dev_mode() or is_test_mode()


def redis_required() -> bool:
    return env_flag("REDIS_REQUIRED", default=not is_development_or_test())


def memory_fallback_allowed() -> bool:
    return (
        is_development_or_test()
        and not redis_required()
        and env_flag("ALLOW_IN_MEMORY_SESSIONS")
    )


def trusted_proxy_networks() -> tuple[IPv4Network | IPv6Network, ...]:
    raw_values = ",".join(
        part
        for name in ("TRUSTED_PROXY_IPS", "TRUSTED_PROXY_CIDRS")
        if (part := os.getenv(name, ""))
    ).split(",")
    networks = []
    for raw_value in raw_values:
        value = raw_value.strip()
        if not value or value == "*":
            continue
        try:
            networks.append(ip_network(value, strict=False))
        except ValueError:
            continue
    return tuple(networks)


def cors_origins() -> list[str]:
    raw = os.getenv("CORS_ORIGINS")
    if raw is None:
        return list(_DEVELOPMENT_ORIGINS) if is_development_or_test() else []
    return [origin.strip() for origin in raw.split(",") if origin.strip()]
