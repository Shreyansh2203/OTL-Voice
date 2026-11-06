import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

os.environ["SESSION_SECRET_KEY"] = "test-secret-key-for-testing-only"
os.environ["TEST_MODE"] = "true"
os.environ["DEV_MODE"] = "true"
os.environ["AUTH_PASSWORD"] = "dummy-password"
os.environ["ALLOW_IN_MEMORY_SESSIONS"] = "true"
os.environ["REDIS_REQUIRED"] = "false"
os.environ["REDIS_URL"] = ""
os.environ["SESSION_COOKIE_SECURE"] = "false"

from backend.core import auth
from backend.core.auth import (
    AuthenticationConfigurationError,
    IdentityProviderUnavailable,
)
from backend.core.token_blocklist import SessionStoreUnavailable
from backend.models import Employee
from backend.services.otl_client import OtlConfigError, OtlError


def _user_mapping():
    return {
        "someone": auth.AuthUser(
            employee_id="10021",
            username="someone",
            password_hash=auth._DUMMY_PASSWORD_HASH,
        )
    }


@pytest.mark.asyncio
async def test_verify_login_identity_provider_unavailable_returns_503():
    """Cover api/v1/auth.py:44-51 - IdentityProviderUnavailable -> 503."""
    from backend.api.v1 import auth as auth_api

    async def boom(*_args, **_kwargs):
        raise IdentityProviderUnavailable("idp down")

    with patch.object(
        auth_api.auth, "get_credential_verifier", return_value=MagicMock(verify=boom)
    ):
        with pytest.raises(HTTPException) as exc:
            await auth_api._verify_login("someone", "password")
    assert exc.value.status_code == 503
    assert exc.value.detail == "Identity verification is temporarily unavailable."
    assert exc.value.headers.get("Retry-After") == "1"


@pytest.mark.asyncio
async def test_verify_login_authentication_error_returns_401():
    """Cover api/v1/auth.py:50-54 - AuthenticationError -> 401."""
    from backend.api.v1 import auth as auth_api

    async def boom(*_args, **_kwargs):
        raise auth.AuthenticationError("bad credentials")

    with patch.object(
        auth_api.auth, "get_credential_verifier", return_value=MagicMock(verify=boom)
    ):
        with pytest.raises(HTTPException) as exc:
            await auth_api._verify_login("someone", "password")
    assert exc.value.status_code == 401
    assert exc.value.detail == "Invalid username or credentials."


@pytest.mark.asyncio
async def test_verify_login_none_verification_returns_401():
    """Cover api/v1/auth.py:55-59 - verification is None -> 401."""
    from backend.api.v1 import auth as auth_api

    async def none_verify(*_args, **_kwargs):
        return None

    with patch.object(
        auth_api.auth,
        "get_credential_verifier",
        return_value=MagicMock(verify=none_verify),
    ):
        with pytest.raises(HTTPException) as exc:
            await auth_api._verify_login("someone", "password")
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_load_active_employee_otl_config_error_returns_503():
    """Cover api/v1/auth.py:74-78 - OtlConfigError -> 503."""
    from backend.api.v1 import auth as auth_api

    verification = auth.AuthVerification(employee_id="10021", username="someone")

    def boom(*_args, **_kwargs):
        raise OtlConfigError("not configured")

    with patch.object(auth_api.otl_client, "service_credential", side_effect=boom):
        with pytest.raises(HTTPException) as exc:
            await auth_api._load_active_employee(verification)
    assert exc.value.status_code == 503
    assert "Employee directory is not configured" in exc.value.detail


@pytest.mark.asyncio
async def test_load_active_employee_otl_error_returns_401():
    """Cover api/v1/auth.py:81-86 - OtlError -> 401."""
    from backend.api.v1 import auth as auth_api

    verification = auth.AuthVerification(employee_id="10021", username="someone")

    async def boom(*_args, **_kwargs):
        raise OtlError(404, "not found")

    with patch.object(
        auth_api.otl_client, "service_credential", return_value=MagicMock()
    ):
        with patch.object(auth_api.otl_client, "aget_worker", side_effect=boom):
            with pytest.raises(HTTPException) as exc:
                await auth_api._load_active_employee(verification)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_load_active_employee_unexpected_exception_returns_500():
    """Cover api/v1/auth.py:87-92 - unexpected Exception -> 500."""
    from backend.api.v1 import auth as auth_api

    verification = auth.AuthVerification(employee_id="10021", username="someone")

    async def boom(*_args, **_kwargs):
        raise RuntimeError("unexpected")

    with patch.object(
        auth_api.otl_client, "service_credential", return_value=MagicMock()
    ):
        with patch.object(auth_api.otl_client, "aget_worker", side_effect=boom):
            with pytest.raises(HTTPException) as exc:
                await auth_api._load_active_employee(verification)
    assert exc.value.status_code == 500


@pytest.mark.asyncio
async def test_load_active_employee_directory_id_mismatch_returns_401():
    """Cover api/v1/auth.py:98-103 - directory_id mismatch -> 401."""
    from backend.api.v1 import auth as auth_api

    verification = auth.AuthVerification(employee_id="10021", username="someone")

    with patch.object(
        auth_api.otl_client, "service_credential", return_value=MagicMock()
    ):
        with patch.object(
            auth_api.otl_client,
            "aget_worker",
            return_value={
                "personNumber": "99999",
                "fullName": "Other",
                "isActive": True,
            },
        ):
            with pytest.raises(HTTPException) as exc:
                await auth_api._load_active_employee(verification)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_load_active_employee_inactive_worker_returns_401():
    """Cover api/v1/auth.py:93-97 - inactive worker -> 401."""
    from backend.api.v1 import auth as auth_api

    verification = auth.AuthVerification(employee_id="10021", username="someone")

    with patch.object(
        auth_api.otl_client, "service_credential", return_value=MagicMock()
    ):
        with patch.object(
            auth_api.otl_client,
            "aget_worker",
            return_value={
                "personNumber": "10021",
                "fullName": "Other",
                "isActive": False,
            },
        ):
            with pytest.raises(HTTPException) as exc:
                await auth_api._load_active_employee(verification)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_issue_session_store_unavailable_returns_503():
    """Cover api/v1/auth.py:115-120 - SessionStoreUnavailable -> 503."""
    from backend.api.v1 import auth as auth_api

    employee = Employee(employee_id="10021", username="someone", full_name="Someone")

    async def boom(*_args, **_kwargs):
        raise SessionStoreUnavailable("store down")

    with patch.object(auth_api.auth, "issue_session", side_effect=boom):
        with pytest.raises(HTTPException) as exc:
            await auth_api._issue_session(employee)
    assert exc.value.status_code == 503
    assert "Session creation is temporarily unavailable" in exc.value.detail


@pytest.mark.asyncio
async def test_refresh_session_destroy_store_unavailable_returns_503():
    """Cover api/v1/auth.py:182-187 - destroy SessionStoreUnavailable -> 503."""
    from fastapi import Request, Response

    from backend.api.v1 import auth as auth_api

    ctx = auth.SessionContext(
        employee_id="10021", username="someone", full_name="Someone"
    )

    def boom(*_args, **_kwargs):
        raise SessionStoreUnavailable("store down")

    mock_request = MagicMock(spec=Request)
    mock_request.cookies = {}
    employee = Employee(employee_id="10021", username="someone", full_name="Someone")

    with patch.object(auth_api.auth, "session_cookie_token", return_value="old-token"):
        with patch.object(auth_api.auth, "destroy", side_effect=boom):
            with patch.object(auth_api, "_load_active_employee", return_value=employee):
                with patch.object(auth_api, "_issue_session", return_value="new-token"):
                    response = Response()
                    with pytest.raises(HTTPException) as exc:
                        await auth_api.refresh_session(mock_request, response, ctx)
    assert exc.value.status_code == 503
    assert "Session rotation is temporarily unavailable" in exc.value.detail


@pytest.mark.asyncio
async def test_refresh_session_no_token_returns_401():
    """Cover api/v1/auth.py:170-174 - no old token -> 401."""
    from fastapi import Request, Response

    from backend.api.v1 import auth as auth_api

    ctx = auth.SessionContext(
        employee_id="10021", username="someone", full_name="Someone"
    )

    mock_request = MagicMock(spec=Request)
    mock_request.cookies = {}

    with patch.object(auth_api.auth, "session_cookie_token", return_value=None):
        response = Response()
        with pytest.raises(HTTPException) as exc:
            await auth_api.refresh_session(mock_request, response, ctx)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_login_otl_config_error_through_endpoint(client):
    """Cover api/v1/auth.py login endpoint OtlConfigError path."""
    with patch.dict(
        os.environ,
        {
            "DEV_MODE": "false",
            "TEST_MODE": "false",
            "AUTH_PASSWORD": "",
            "AUTH_USERS": "",
            "OIDC_ISSUER": "",
            "OIDC_AUDIENCE": "",
            "OIDC_JWKS_URL": "",
        },
    ):
        with patch(
            "backend.main.auth_rate_limiter.is_allowed",
            new=AsyncMock(return_value=True),
        ):
            # No verifier configured -> 503 at _verify_login, before otl_client is reached
            health = client.get("/api/health")
            csrf_token = health.headers["X-CSRF-Token"]
            response = client.post(
                "/api/auth/login",
                json={"username": "10021", "password": "whatever"},
                headers={"X-CSRF-Token": csrf_token},
            )
    assert response.status_code == 503
    assert "Authentication is not configured" in response.json()["detail"]


def test_get_credential_verifier_auth_users_duplicate_keys():
    """Cover core/auth.py:464-467 - duplicate case-insensitive identifiers."""
    from backend.core import auth as core_auth

    raw = '{"10021": "hash1", "10021": "hash2"}'
    with pytest.raises(AuthenticationConfigurationError, match="valid JSON object"):
        core_auth.LocalCredentialVerifier.from_mapping(raw)


def test_get_credential_verifier_auth_users_too_many():
    """Cover core/auth.py:421-422 - too many users."""
    from backend.core import auth as core_auth

    raw = "{" + ",".join(f'"user{i}": "hash{i}"' for i in range(10001)) + "}"
    with pytest.raises(AuthenticationConfigurationError, match="too many users"):
        core_auth.LocalCredentialVerifier.from_mapping(raw)


def test_get_credential_verifier_auth_users_incomplete():
    """Cover core/auth.py:459-462 - incomplete user."""
    from backend.core import auth as core_auth

    raw = '{"10021": {"employeeId": "", "username": "", "password": ""}}'
    with pytest.raises(AuthenticationConfigurationError, match="incomplete"):
        core_auth.LocalCredentialVerifier.from_mapping(raw)


def test_get_credential_verifier_auth_users_bad_employee_id_type():
    """Cover core/auth.py:438-443 - employeeId must be str or int."""
    from backend.core import auth as core_auth

    raw = '{"10021": {"employeeId": 3.14, "username": "u", "password": "hash"}}'
    with pytest.raises(AuthenticationConfigurationError, match="employeeId"):
        core_auth.LocalCredentialVerifier.from_mapping(raw)


def test_get_credential_verifier_auth_users_bad_username_type():
    """Cover core/auth.py:444-447 - username must be str."""
    from backend.core import auth as core_auth

    raw = '{"10021": {"username": 123, "password": "hash"}}'
    with pytest.raises(AuthenticationConfigurationError, match="username"):
        core_auth.LocalCredentialVerifier.from_mapping(raw)


def test_get_credential_verifier_auth_users_bad_password_type():
    """Cover core/auth.py:450-454 - password must be str."""
    from backend.core import auth as core_auth

    raw = '{"10021": {"password": 123}}'
    with pytest.raises(AuthenticationConfigurationError, match="password"):
        core_auth.LocalCredentialVerifier.from_mapping(raw)


def test_get_credential_verifier_auth_users_value_not_str_or_dict():
    """Cover core/auth.py:455-458 - value must be str or dict."""
    from backend.core import auth as core_auth

    raw = '{"10021": [1, 2, 3]}'
    with pytest.raises(AuthenticationConfigurationError, match="values must be"):
        core_auth.LocalCredentialVerifier.from_mapping(raw)


def test_validate_oidc_endpoint_http_in_dev():
    """Cover core/auth.py:374-377 - HTTP allowed in dev/test."""
    from backend.core import auth as core_auth

    with patch.dict(os.environ, {"DEV_MODE": "true", "TEST_MODE": "true"}):
        core_auth._validate_oidc_endpoint("http://localhost/keys", "OIDC_JWKS_URL")


def test_validate_oidc_endpoint_http_in_prod_fails():
    """Cover core/auth.py:374-377 - HTTP not allowed in prod."""
    from backend.core import auth as core_auth

    with patch.dict(
        os.environ, {"DEV_MODE": "false", "TEST_MODE": "false"}, clear=False
    ):
        with pytest.raises(AuthenticationConfigurationError, match="HTTPS"):
            core_auth._validate_oidc_endpoint(
                "http://example.com/keys", "OIDC_JWKS_URL"
            )


def test_validate_oidc_endpoint_credentials_rejected():
    """Cover core/auth.py:366-367 - credentials in URL rejected."""
    from backend.core import auth as core_auth

    with patch.dict(os.environ, {"DEV_MODE": "true", "TEST_MODE": "true"}):
        with pytest.raises(AuthenticationConfigurationError, match="credentials"):
            core_auth._validate_oidc_endpoint(
                "http://user:pass@example.com/keys", "OIDC_JWKS_URL"
            )


def test_validate_oidc_endpoint_query_rejected():
    """Cover core/auth.py:368 - query string rejected."""
    from backend.core import auth as core_auth

    with patch.dict(os.environ, {"DEV_MODE": "true", "TEST_MODE": "true"}):
        with pytest.raises(
            AuthenticationConfigurationError, match="without credentials"
        ):
            core_auth._validate_oidc_endpoint(
                "http://example.com/keys?x=1", "OIDC_JWKS_URL"
            )


def test_read_claim_nested_path():
    """Cover core/auth.py:382-389 - nested claim path reading."""
    from backend.core import auth as core_auth

    payload = {"identity": {"person_number": "10021"}}
    assert core_auth._read_claim(payload, "identity.person_number") == "10021"
    assert core_auth._read_claim(payload, "identity.missing") is None
    assert core_auth._read_claim(payload, "missing.person_number") is None


def test_read_claim_bool_rejected():
    """Cover core/auth.py:386-387 - bool values rejected."""
    from backend.core import auth as core_auth

    assert core_auth._read_claim({"flag": True}, "flag") is None


def test_read_claim_empty_string_rejected():
    """Cover core/auth.py:388-389 - empty string rejected."""
    from backend.core import auth as core_auth

    assert core_auth._read_claim({"name": "  "}, "name") is None


def test_jwt_secret_production_too_short():
    """Cover core/auth.py:666-669 - production secret too short."""
    from backend.core import auth as core_auth

    with patch.dict(
        os.environ,
        {"SESSION_SECRET_KEY": "short", "DEV_MODE": "false", "TEST_MODE": "false"},
        clear=False,
    ):
        with pytest.raises(RuntimeError, match="at least 32 bytes"):
            core_auth._jwt_secret()


def test_jwt_secret_production_missing():
    """Cover core/auth.py:663-665 - production secret required."""
    from backend.core import auth as core_auth

    with patch.dict(
        os.environ,
        {"SESSION_SECRET_KEY": "", "DEV_MODE": "false", "TEST_MODE": "false"},
        clear=False,
    ):
        core_auth._fallback_jwt_secret = None
        with pytest.raises(RuntimeError, match="required outside development"):
            core_auth._jwt_secret()


def test_session_ttl_invalid():
    """Cover core/auth.py:676-677 - invalid TTL."""
    from backend.core import auth as core_auth

    with patch.dict(os.environ, {"SESSION_TTL_SECONDS": "not-a-number"}):
        with pytest.raises(RuntimeError, match="must be an integer"):
            core_auth._ttl_seconds()


def test_cookie_secure_default_true():
    """Cover core/auth.py:680-683 - default secure is True."""
    from backend.core import auth as core_auth

    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("SESSION_COOKIE_SECURE", None)
        assert core_auth.cookie_secure() is True


def test_session_samesite_none_requires_secure():
    """Cover core/auth.py:694-697 - samesite=none requires secure."""
    from backend.core import auth as core_auth

    with patch.dict(
        os.environ,
        {"SESSION_COOKIE_SAMESITE": "none", "SESSION_COOKIE_SECURE": "false"},
    ):
        with pytest.raises(RuntimeError, match="requires SESSION_COOKIE_SECURE=true"):
            core_auth._session_samesite()


def test_session_samesite_invalid_defaults_to_strict():
    """Cover core/auth.py:692-693 - invalid samesite defaults to strict."""
    from backend.core import auth as core_auth

    with patch.dict(os.environ, {"SESSION_COOKIE_SAMESITE": "invalid"}):
        assert core_auth._session_samesite() == "strict"


def test_current_session_store_unavailable_returns_503():
    """Cover core/auth.py:898-903 - SessionStoreUnavailable -> 503."""
    import jwt as pyjwt

    from backend.core import auth as core_auth

    token = pyjwt.encode(
        {
            "sub": "10021",
            "username": "someone",
            "iss": "otl-voice",
            "aud": "otl-voice-web",
            "iat": 1,
            "exp": 9999999999,
            "jti": "abc",
        },
        core_auth._jwt_secret(),
        algorithm="HS256",
    )
    unavailable = MagicMock()
    unavailable.get_session = AsyncMock(side_effect=SessionStoreUnavailable("down"))

    with patch.object(core_auth, "_blocklist", return_value=unavailable):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(core_auth.current_session(otl_session=token))
    assert exc.value.status_code == 503


def test_destroy_invalid_token_returns_silently():
    """Cover core/auth.py:886-888 - invalid token in destroy."""
    from backend.core import auth as core_auth

    asyncio.run(core_auth.destroy("not-a-jwt"))
    asyncio.run(core_auth.destroy(""))


def test_activate_session_invalid_token_raises_runtime():
    """Cover core/auth.py:828-829 - invalid token in activate_session."""
    from backend.core import auth as core_auth

    employee = Employee(employee_id="10021", username="someone", full_name="Someone")
    with pytest.raises(RuntimeError, match="Refusing to activate"):
        asyncio.run(core_auth.activate_session("not-a-jwt", employee))


def test_activate_session_identity_mismatch_raises_runtime():
    """Cover core/auth.py:830-834 - identity mismatch in activate_session."""
    from backend.core import auth as core_auth

    employee = Employee(employee_id="10021", username="someone", full_name="Someone")
    import jwt as pyjwt

    token = pyjwt.encode(
        {
            "sub": "other",
            "username": "other",
            "iss": "otl-voice",
            "aud": "otl-voice-web",
            "iat": 1,
            "exp": 9999999999,
            "jti": "abc",
        },
        core_auth._jwt_secret(),
        algorithm="HS256",
    )
    with pytest.raises(RuntimeError, match="does not match"):
        asyncio.run(core_auth.activate_session(token, employee))


def test_float_env_invalid():
    """Cover core/auth.py:915-916 - invalid float env."""
    from backend.core import auth as core_auth

    with patch.dict(os.environ, {"OIDC_JWKS_CACHE_SECONDS": "not-a-number"}):
        with pytest.raises(AuthenticationConfigurationError, match="must be numeric"):
            core_auth._float_env("OIDC_JWKS_CACHE_SECONDS", 300.0)


def test_clear_oidc_caches():
    """Cover core/auth.py:931-933 - clear caches."""
    from backend.core import auth as core_auth

    core_auth._JWKS_CACHE[("issuer", "url")] = object()
    core_auth._DISCOVERY_CACHE["issuer"] = (999999.0, "url")
    core_auth._clear_oidc_caches()
    assert core_auth._JWKS_CACHE == {}
    assert core_auth._DISCOVERY_CACHE == {}


# --- health endpoint ---


@pytest.mark.asyncio
async def test_health_otl_timeout(client, monkeypatch):
    """Cover api/v1/health.py:48-49 - OTL health check timeout."""
    from fastapi import Response

    from backend.api.v1 import health as health_api

    async def slow_validate(*_args, **_kwargs):
        await asyncio.sleep(10)
        return {"ok": True}

    with patch.object(health_api.otl_client, "avalidate", side_effect=slow_validate):
        with patch.object(
            health_api.otl_client, "service_credential", return_value=MagicMock()
        ):
            with patch.object(
                health_api.auth,
                "current_session",
                return_value=auth.SessionContext(
                    employee_id="testuser", username="testuser", full_name="Test User"
                ),
            ):
                with pytest.raises(HTTPException) as exc:
                    await health_api.health_otl(Response(), None)
    assert exc.value.status_code == 504


def test_health_admin_key_missing(client, mock_otl_client):
    """Cover api/v1/health.py:19-22 - admin key not configured."""
    from backend import main
    from backend.core import auth

    main.app.dependency_overrides[auth.current_session] = lambda: auth.SessionContext(
        employee_id="testuser", username="testuser", full_name="Test User"
    )
    try:
        with patch.dict(os.environ, {"ADMIN_API_KEY": ""}, clear=False):
            response = client.post("/api/admin/refresh-catalogue")
        assert response.status_code == 403
        assert "Admin key not configured" in response.json()["detail"]
    finally:
        main.app.dependency_overrides.pop(auth.current_session, None)


def test_health_admin_key_wrong(client, mock_otl_client):
    """Cover api/v1/health.py:24-30 - admin key mismatch."""
    from backend import main
    from backend.core import auth

    main.app.dependency_overrides[auth.current_session] = lambda: auth.SessionContext(
        employee_id="testuser", username="testuser", full_name="Test User"
    )
    try:
        with patch.dict(os.environ, {"ADMIN_API_KEY": "real-key-12345"}, clear=False):
            response = client.post(
                "/api/admin/refresh-catalogue",
                headers={"X-Admin-Key": "wrong-key"},
            )
        assert response.status_code == 403
        assert "Admin key required" in response.json()["detail"]
    finally:
        main.app.dependency_overrides.pop(auth.current_session, None)


# --- chat sanitization ---


def test_sanitize_assignments_empty_text():
    """Cover services/chat.py:65 - empty text returns early."""
    from backend.services.chat import _sanitize_assignments

    assert _sanitize_assignments("") == ""
    assert _sanitize_assignments(None) is None


# --- auth API: demo mode employee loading ---


@pytest.mark.asyncio
async def test_load_active_employee_demo_mode(client, monkeypatch):
    """Cover api/v1/auth.py:66-71 - demo mode employee in _load_active_employee."""
    from backend.api.v1 import auth as auth_api

    verification = auth.AuthVerification(
        employee_id=auth.DEMO_EMPLOYEE_ID, username="demo"
    )

    with patch.dict(os.environ, {"DEMO_MODE": "true"}, clear=False):
        employee = await auth_api._load_active_employee(verification)
    assert employee.employee_id == auth.DEMO_EMPLOYEE_ID
    assert employee.username == "demo"
    assert employee.full_name == "Demo User"


# --- auth API: logout with SessionStoreUnavailable ---


@pytest.mark.asyncio
async def test_logout_session_store_unavailable(client, monkeypatch):
    """Cover api/v1/auth.py:151-158 - logout with SessionStoreUnavailable."""
    from fastapi import Request, Response

    from backend.api.v1 import auth as auth_api

    def boom(*_args, **_kwargs):
        raise SessionStoreUnavailable("store down")

    mock_request = MagicMock(spec=Request)
    mock_request.cookies = {}

    with patch.object(auth_api.auth, "session_cookie_token", return_value="old-token"):
        with patch.object(auth_api.auth, "destroy", side_effect=boom):
            response = Response()
            result = await auth_api.logout(mock_request, response)
    assert result.status_code == 503
    assert "Session revocation is temporarily unavailable" in result.body.decode()
