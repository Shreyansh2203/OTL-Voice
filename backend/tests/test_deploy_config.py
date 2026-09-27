from __future__ import annotations

import asyncio
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any, cast

import pytest
import yaml
from fastapi.testclient import TestClient
from uvicorn._types import ASGI3Application
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from backend import main
from backend.core.config import trusted_proxy_networks

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DOCKERFILE = REPO_ROOT / "Dockerfile"
COMPOSE_FILE = REPO_ROOT / "deploy" / "docker-compose.yml"
UVICORN_DEFAULT_FORWARDED_ALLOW_IPS = "127.0.0.1"
_PROXY_ADDRESS = "172.30.7.3"
_REAL_CLIENT = "203.0.113.9"
_FORGED_CLIENT = "198.51.100.7"


def _load_preflight():
    path = REPO_ROOT / "deploy" / "preflight.py"
    spec = importlib.util.spec_from_file_location("deploy_preflight", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _dockerfile_cmd() -> list[str]:
    text = DOCKERFILE.read_text(encoding="utf-8")
    match = re.search(r"^CMD (\[.*\])\s*$", text, re.MULTILINE)
    assert match is not None, "Dockerfile has no exec-form CMD"
    return list(json.loads(match.group(1)))


def _shipped_forwarded_allow_ips() -> str:
    """The trusted-host value uvicorn would use for the shipped CMD."""
    argv = _dockerfile_cmd()
    for index, argument in enumerate(argv):
        if argument == "--forwarded-allow-ips" and index + 1 < len(argv):
            return argv[index + 1]
        if argument.startswith("--forwarded-allow-ips="):
            return argument.split("=", 1)[1]
    return UVICORN_DEFAULT_FORWARDED_ALLOW_IPS


def _shipped_app() -> Any:
    return ProxyHeadersMiddleware(
        cast("ASGI3Application", main.app),
        trusted_hosts=_shipped_forwarded_allow_ips(),
    )


def _scope(peer: tuple[str, int], forwarded_for: str) -> dict[str, Any]:
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/auth/login",
        "raw_path": b"/api/auth/login",
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"timesheet.example.com"),
            (b"x-forwarded-for", forwarded_for.encode("latin1")),
        ],
        "client": peer,
        "server": ("127.0.0.1", 8000),
    }


def test_shipped_container_command_does_not_trust_every_forwarded_header():
    argv = _dockerfile_cmd()

    assert "--forwarded-allow-ips=*" not in argv
    assert "*" not in [
        value
        for index, value in enumerate(argv)
        if value == "--forwarded-allow-ips"
        or value.startswith("--forwarded-allow-ips=")
    ]


def test_shipped_server_never_rewrites_client_from_a_forged_forwarded_header():
    seen: list[Any] = []

    async def capture(scope, receive, send):  # noqa: ANN001, ANN202
        seen.append(scope.get("client"))

    app = ProxyHeadersMiddleware(
        cast("ASGI3Application", capture),
        trusted_hosts=_shipped_forwarded_allow_ips(),
    )
    forwarded_for = f"{_FORGED_CLIENT}, {_REAL_CLIENT}"
    scope = _scope((_PROXY_ADDRESS, 51234), forwarded_for)

    async def receive():  # noqa: ANN202
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(_message):  # noqa: ANN202
        return None

    asyncio.run(app(scope, receive, send))

    assert seen == [(_PROXY_ADDRESS, 51234)]
    assert _FORGED_CLIENT not in str(seen)
    assert _REAL_CLIENT not in str(seen)


def test_forged_leftmost_forwarded_header_does_not_open_a_new_rate_limit_bucket(
    monkeypatch,
):
    monkeypatch.setenv("DEV_MODE", "true")
    monkeypatch.setenv("TEST_MODE", "false")
    monkeypatch.setenv("REDIS_REQUIRED", "false")
    monkeypatch.setenv("ALLOW_IN_MEMORY_SESSIONS", "true")
    monkeypatch.setenv("REDIS_URL", "")
    monkeypatch.setenv("TRUSTED_PROXY_IPS", "")
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", "172.30.7.0/24")
    from backend.core.limiter import auth_rate_limiter

    auth_rate_limiter._local_requests.clear()
    with TestClient(_shipped_app(), client=(_PROXY_ADDRESS, 51234)) as client:
        statuses = [
            client.get(
                "/api/auth/session",
                headers={"X-Forwarded-For": f"198.51.100.{index}, {_REAL_CLIENT}"},
            ).status_code
            for index in range(11)
        ]
    auth_rate_limiter._local_requests.clear()

    assert statuses[0] == 401
    assert 429 not in statuses[:10], (
        "each forged leftmost X-Forwarded-For entry opened a fresh rate-limit bucket"
    )
    assert statuses[10] == 429


def test_trusted_proxy_cidr_and_ip_settings_are_interchangeable(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_IPS", "10.0.0.5")
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", "")
    assert tuple(str(network) for network in trusted_proxy_networks()) == (
        "10.0.0.5/32",
    )

    monkeypatch.setenv("TRUSTED_PROXY_IPS", "")
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", "172.30.7.0/24")
    assert tuple(str(network) for network in trusted_proxy_networks()) == (
        "172.30.7.0/24",
    )

    monkeypatch.setenv("TRUSTED_PROXY_IPS", "10.0.0.5")
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", "172.30.7.0/24")
    assert tuple(str(network) for network in trusted_proxy_networks()) == (
        "10.0.0.5/32",
        "172.30.7.0/24",
    )


def test_compose_does_not_shadow_the_operator_trusted_proxy_setting():
    compose = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
    environment = compose["services"]["app"]["environment"]

    assert "TRUSTED_PROXY_CIDRS" not in environment
    assert "TRUSTED_PROXY_IPS" not in environment
    assert not [key for key in environment if key.startswith("TRUSTED_PROXY")], (
        "compose still overrides the operator's trusted-proxy setting"
    )


def test_compose_bridge_network_is_a_narrow_subnet_not_a_whole_bridge_range():
    compose = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
    subnets = [
        config["subnet"] for config in compose["networks"]["default"]["ipam"]["config"]
    ]

    assert subnets == ["172.30.7.0/24"]
    from ipaddress import ip_network

    assert ip_network(subnets[0]).num_addresses <= 256


def test_compose_security_flags_are_pinned_and_not_operator_overridable():
    compose = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
    environment = compose["services"]["app"]["environment"]

    for name in (
        "TEST_MODE",
        "DEV_MODE",
        "CSP_DEV_MODE",
        "REDIS_REQUIRED",
        "SESSION_COOKIE_SECURE",
    ):
        assert environment[name] in {"true", "false"}
        assert "${" not in environment[name]


def _production_values(**overrides: str) -> dict[str, str]:
    values = {
        "SESSION_SECRET_KEY": "s" * 48,
        "ADMIN_API_KEY": "a" * 32,
        "OTL_BASE_URL": "https://otl.acme-internal.net/hcmRestApi/resources/11.13.18.05",
        "OTL_SERVICE_USERNAME": "integration.service@acme-internal.net",
        "OTL_SERVICE_PASSWORD": "p" * 24,
        "OCI_REGION": "us-ashburn-1",
        "OCI_COMPARTMENT_ID": "ocid1.compartment.oc1..aaa",
        "OCI_CONFIG_FILE": "/home/appuser/.oci/config",
        "AUTH_USERS": json.dumps(
            {"10021": "scrypt$32768$8$1$AAAAAAAAAAAAAAAAAAAAAA==$AAAA"}
        ),
        "REDIS_URL": "rediss://redis.acme-internal.net:6379/0",
        "SESSION_COOKIE_SECURE": "true",
        "SESSION_COOKIE_SAMESITE": "lax",
        "REDIS_REQUIRED": "true",
        "ALLOW_IN_MEMORY_SESSIONS": "false",
        "TRUSTED_PROXY_IPS": "",
        "TRUSTED_PROXY_CIDRS": "172.30.7.0/24",
    }
    values.update(overrides)
    return values


def test_production_preflight_passes_a_complete_configuration():
    preflight = _load_preflight()

    assert preflight._check(_production_values(), "production") == []


@pytest.mark.parametrize("flag", ["TEST_MODE", "DEV_MODE", "CSP_DEV_MODE"])
@pytest.mark.parametrize("value", ["true", "TRUE", "1", "yes", "on"])
def test_production_preflight_refuses_relaxed_security_flags(flag, value):
    preflight = _load_preflight()

    errors = preflight._check(_production_values(**{flag: value}), "production")

    assert any(flag in error for error in errors), errors


@pytest.mark.parametrize("value", ["false", "0", "no", "off"])
def test_production_preflight_refuses_a_disabled_project_authorisation_check(value):
    preflight = _load_preflight()

    errors = preflight._check(_production_values(STRICT_ASSIGNMENT=value), "production")

    assert any("STRICT_ASSIGNMENT" in error for error in errors), errors


def test_production_preflight_requires_a_usable_trusted_proxy_range():
    preflight = _load_preflight()

    missing = preflight._check(
        _production_values(TRUSTED_PROXY_CIDRS="", TRUSTED_PROXY_IPS=""), "production"
    )
    placeholder = preflight._check(
        _production_values(
            TRUSTED_PROXY_CIDRS="", TRUSTED_PROXY_IPS="replace-with-proxy"
        ),
        "production",
    )

    assert any("TRUSTED_PROXY" in error for error in missing)
    assert any("TRUSTED_PROXY" in error for error in placeholder)
