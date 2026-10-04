from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from backend.core import auth

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _load_readycheck():
    path = REPO_ROOT / "deploy" / "readycheck.py"
    spec = importlib.util.spec_from_file_location("deploy_readycheck", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


readycheck = _load_readycheck()


class _Response:
    """The little of urlopen's response the probe actually uses."""

    def __init__(self, payload: dict[str, Any], status: int = 200) -> None:
        self._body = json.dumps(payload).encode("utf-8")
        self.status = status

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def _captured_request(monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]) -> Any:
    captured: dict[str, Any] = {}

    def fake_urlopen(request, timeout=None, context=None):  # noqa: ANN001, ANN202
        captured["request"] = request
        return _Response(payload)

    monkeypatch.setattr(readycheck, "urlopen", fake_urlopen)
    return captured


# ── the probe has to speak the same authentication the server accepts ───────────


def test_the_dependency_probe_sends_a_session_cookie_not_a_bearer_token(monkeypatch):
    # /api/health/otl depends on auth.current_session, which reads the session cookie;
    # bearer auth is deliberately unsupported (backend/main.py rejects it). A bearer
    # header made the container permanently unhealthy, so nginx never started.
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")
    monkeypatch.delenv("READINESS_AUTH_COOKIE_NAME", raising=False)
    captured = _captured_request(monkeypatch, {"status": "connected"})

    readycheck._get("https://localhost/api/health/otl", "a-session-token")

    headers = captured["request"].headers
    assert headers["Cookie"] == "otl_session=a-session-token"
    assert "Authorization" not in headers


@pytest.mark.parametrize("secure", ["true", "1", "yes", None])
def test_the_cookie_name_follows_the_secure_prefix_the_server_uses(monkeypatch, secure):
    # backend.core.auth prefixes the cookie with __Host- whenever SESSION_COOKIE_SECURE
    # is not explicitly off, and FastAPI binds that alias when the app is imported, so
    # the probe has to derive the same name rather than guess one.
    if secure is None:
        monkeypatch.delenv("SESSION_COOKIE_SECURE", raising=False)
    else:
        monkeypatch.setenv("SESSION_COOKIE_SECURE", secure)
    monkeypatch.delenv("READINESS_AUTH_COOKIE_NAME", raising=False)
    captured = _captured_request(monkeypatch, {"status": "connected"})

    readycheck._get("https://localhost/api/health/otl", "token")

    expected = auth._session_cookie_name()
    assert captured["request"].headers["Cookie"] == f"{expected}=token"
    if secure is None:
        assert expected == "__Host-otl_session", (
            "production defaults to the secure name"
        )


@pytest.mark.parametrize("secure", ["false", "0", "no", "off"])
def test_an_insecure_deployment_sends_the_unprefixed_name(monkeypatch, secure):
    monkeypatch.setenv("SESSION_COOKIE_SECURE", secure)
    monkeypatch.delenv("READINESS_AUTH_COOKIE_NAME", raising=False)
    captured = _captured_request(monkeypatch, {"status": "connected"})

    readycheck._get("https://localhost/api/health/otl", "token")

    assert captured["request"].headers["Cookie"] == "otl_session=token"


def test_the_cookie_name_can_be_overridden(monkeypatch):
    monkeypatch.setenv("READINESS_AUTH_COOKIE_NAME", "custom_session")
    captured = _captured_request(monkeypatch, {"status": "connected"})

    readycheck._get("https://localhost/api/health/otl", "token")

    assert captured["request"].headers["Cookie"] == "custom_session=token"


def test_the_liveness_probe_sends_no_credentials_at_all(monkeypatch):
    # /api/health is unauthenticated, so it must not carry the readiness token.
    captured = _captured_request(monkeypatch, {"status": "ok"})

    readycheck._get("https://localhost/api/health")

    headers = captured["request"].headers
    assert "Cookie" not in headers
    assert "Authorization" not in headers


# ── main() wiring ──────────────────────────────────────────────────────────────


def test_main_passes_the_readiness_token_to_the_dependency_probe(monkeypatch, tmp_path):
    token_file = tmp_path / "session.token"
    token_file.write_text("provisioned-token\n", encoding="utf-8")
    seen: list[tuple[str, str | None]] = []

    def fake_get(url: str, token: str | None = None) -> None:
        seen.append((url, token))

    monkeypatch.setenv("READINESS_URL", "https://localhost/api/health")
    monkeypatch.setenv("READINESS_OTL_URL", "https://localhost/api/health/otl")
    monkeypatch.setenv("READINESS_AUTH_TOKEN_FILE", str(token_file))
    monkeypatch.setattr(readycheck, "_get", fake_get)

    assert readycheck.main() == 0
    assert seen == [
        ("https://localhost/api/health", None),
        ("https://localhost/api/health/otl", "provisioned-token"),
    ]


def test_main_fails_closed_when_the_dependency_probe_rejects_the_probe(
    monkeypatch, tmp_path
):
    # A 401 is what the old bearer header produced, and it has to stay a failure:
    # readiness that passes while the OTL path is unauthenticated is worse than none.
    token_file = tmp_path / "session.token"
    token_file.write_text("provisioned-token", encoding="utf-8")
    calls: list[str] = []

    def fake_get(url: str, token: str | None = None) -> None:
        calls.append(url)
        if "otl" in url:
            raise RuntimeError("readiness endpoint returned HTTP 401")

    monkeypatch.setenv("READINESS_URL", "https://localhost/api/health")
    monkeypatch.setenv("READINESS_OTL_URL", "https://localhost/api/health/otl")
    monkeypatch.setenv("READINESS_REQUIRE_OTL", "true")
    monkeypatch.setenv("READINESS_AUTH_TOKEN_FILE", str(token_file))
    monkeypatch.setattr(readycheck, "_get", fake_get)

    assert readycheck.main() == 1
    assert len(calls) == 2


def test_main_refuses_to_run_without_a_token_file(monkeypatch):
    monkeypatch.setenv("READINESS_URL", "https://localhost/api/health")
    monkeypatch.setenv("READINESS_OTL_URL", "https://localhost/api/health/otl")
    monkeypatch.delenv("READINESS_AUTH_TOKEN_FILE", raising=False)
    monkeypatch.setattr(readycheck, "_get", lambda *args, **kwargs: None)

    assert readycheck.main() == 1
