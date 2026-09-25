import json
import os
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

from backend.core import auth
from backend.core.auth import (
    AuthenticationConfigurationError,
    LocalCredentialVerifier,
    _clear_oidc_caches,
    get_credential_verifier,
    hash_scrypt_password,
)
from backend.core.token_blocklist import SessionStoreUnavailable


@pytest.fixture(scope="module")
def password_hash():
    return hash_scrypt_password("correct horse battery staple")


@pytest.fixture(scope="module")
def signing_material():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = json.loads(
        jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key())
    )
    public_jwk.update({"kid": "test-key", "alg": "RS256", "use": "sig"})
    return private_key, public_jwk


def _oidc_token(private_key, **overrides):
    now = datetime.now(UTC)
    claims = {
        "iss": "https://identity.example.com",
        "aud": "otl-api",
        "sub": "directory-subject",
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "identity": {"person_number": "10021"},
        "preferred_username": "employee10021",
    }
    claims.update(overrides)
    return jwt.encode(
        claims,
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )


def test_scrypt_credentials_are_per_user_and_unknown_users_fail():
    encoded = hash_scrypt_password("user-specific-password")
    verifier = LocalCredentialVerifier.from_mapping(json.dumps({"10021": encoded}))
    assert verifier._users.keys() == {"10021"}


@pytest.mark.asyncio
async def test_scrypt_verifier_accepts_only_mapped_user(password_hash):
    verifier = LocalCredentialVerifier.from_mapping(
        json.dumps({"10021": password_hash})
    )
    verified = await verifier.verify("10021", "correct horse battery staple")
    assert verified is not None
    assert verified.employee_id == "10021"
    assert await verifier.verify("10022", "correct horse battery staple") is None
    assert await verifier.verify("10021", "wrong password") is None


def test_invalid_auth_users_configuration_fails_closed(password_hash):
    invalid_hashes = [
        "{",
        json.dumps({}),
        json.dumps({"10021": "plaintext-password"}),
        json.dumps({"10021": {"employeeId": None, "password": password_hash}}),
        json.dumps({"10021": password_hash, "10021 ": password_hash}),
    ]
    for raw_mapping in invalid_hashes:
        with pytest.raises(AuthenticationConfigurationError):
            LocalCredentialVerifier.from_mapping(raw_mapping)


def test_production_ignores_legacy_password_and_fails_closed(client, mock_otl_client):
    with (
        patch.dict(
            os.environ,
            {
                "DEV_MODE": "false",
                "TEST_MODE": "false",
                "AUTH_PASSWORD": "production-shared-password",
                "AUTH_USERS": "",
                "OIDC_ISSUER": "",
                "OIDC_AUDIENCE": "",
                "OIDC_JWKS_URL": "",
            },
        ),
        patch(
            "backend.main.auth_rate_limiter.is_allowed",
            new=AsyncMock(return_value=True),
        ),
    ):
        health = client.get("/api/health")
        csrf_token = health.headers["X-CSRF-Token"]
        response = client.post(
            "/api/auth/login",
            json={"username": "10021", "password": "arbitrary-password"},
            headers={"X-CSRF-Token": csrf_token},
        )
    assert response.status_code == 503
    assert response.json()["detail"] == "Authentication is not configured."
    mock_otl_client.aget_worker.assert_not_awaited()


def test_login_uses_per_user_scrypt_mapping(client, mock_otl_client, password_hash):
    mock_otl_client.aget_worker.return_value = {
        "personNumber": "10021",
        "fullName": "Employee Name",
        "isActive": True,
    }
    env = {
        "OIDC_ISSUER": "",
        "OIDC_AUDIENCE": "",
        "OIDC_JWKS_URL": "",
        "AUTH_USERS": json.dumps({"10021": password_hash}),
    }
    with patch.dict(os.environ, env):
        rejected = client.post(
            "/api/auth/login",
            json={"username": "10022", "password": "correct horse battery staple"},
        )
        response = client.post(
            "/api/auth/login",
            json={
                "username": "10021",
                "password": "correct horse battery staple",
            },
        )
    assert rejected.status_code == 401
    assert response.status_code == 200
    assert response.json()["employee"]["employeeId"] == "10021"
    assert "sessionToken" not in response.json()
    set_cookie = response.headers.get_list("set-cookie")
    session_cookie = next(value for value in set_cookie if "otl_session=" in value)
    assert "HttpOnly" in session_cookie
    assert "SameSite=strict" in session_cookie
    session_token = client.cookies.get("otl_session")
    client.cookies.clear()
    bearer_response = client.get(
        "/api/auth/session",
        headers={"Authorization": f"Bearer {session_token}"},
    )
    assert bearer_response.status_code == 401


@pytest.mark.asyncio
async def test_oidc_validation_is_strict_and_uses_cached_jwks(signing_material):
    private_key, public_jwk = signing_material
    fetch_json = AsyncMock(return_value={"keys": [public_jwk]})
    env = {
        "OIDC_ISSUER": "https://identity.example.com",
        "OIDC_AUDIENCE": "otl-api",
        "OIDC_JWKS_URL": "https://identity.example.com/keys",
        "OIDC_ALGORITHMS": "RS256",
        "OIDC_PERSON_NUMBER_CLAIM": "identity.person_number",
        "OIDC_USERNAME_CLAIM": "preferred_username",
    }
    _clear_oidc_caches()
    with (
        patch.dict(os.environ, env),
        patch("backend.core.auth._fetch_json", fetch_json),
    ):
        verifier = get_credential_verifier()
        token = _oidc_token(private_key)
        verified = await verifier.verify("attacker-claimed-id", token)
        assert verified is not None
        assert verified.employee_id == "10021"
        assert (
            await verifier.verify("10021", _oidc_token(private_key, aud="other"))
            is None
        )
        expired = _oidc_token(
            private_key,
            exp=datetime.now(UTC) - timedelta(minutes=1),
            iat=datetime.now(UTC) - timedelta(minutes=10),
        )
        assert await verifier.verify("10021", expired) is None
        wrong_issuer = _oidc_token(private_key, iss="https://attacker.example.com")
        assert await verifier.verify("10021", wrong_issuer) is None
        missing_claim = _oidc_token(private_key, identity={})
        assert await verifier.verify("10021", missing_claim) is None
        symmetric_token = jwt.encode(
            {
                "iss": "https://identity.example.com",
                "aud": "otl-api",
                "sub": "10021",
                "iat": datetime.now(UTC),
                "exp": datetime.now(UTC) + timedelta(minutes=5),
            },
            "not-an-oidc-signing-secret-at-least-32-bytes",
            algorithm="HS256",
            headers={"kid": "test-key"},
        )
        assert await verifier.verify("10021", symmetric_token) is None
        assert await verifier.verify("10021", "not-a-jwt") is None
    assert fetch_json.await_count == 1
    _clear_oidc_caches()


def test_development_without_explicit_verifier_never_accepts_arbitrary_password():
    env = {
        "DEV_MODE": "true",
        "TEST_MODE": "true",
        "AUTH_PASSWORD": "",
        "AUTH_USERS": "",
        "OIDC_ISSUER": "",
        "OIDC_AUDIENCE": "",
        "OIDC_JWKS_URL": "",
    }
    with patch.dict(os.environ, env, clear=False):
        with pytest.raises(AuthenticationConfigurationError):
            get_credential_verifier()


def test_oidc_rejects_symmetric_algorithm_configuration():
    env = {
        "OIDC_ISSUER": "https://identity.example.com",
        "OIDC_AUDIENCE": "otl-api",
        "OIDC_ALGORITHMS": "HS256",
        "AUTH_USERS": "",
    }
    with patch.dict(os.environ, env):
        with pytest.raises(AuthenticationConfigurationError):
            get_credential_verifier()


def test_oidc_login_binds_session_to_claim_not_submitted_username(
    client, mock_otl_client, signing_material
):
    private_key, public_jwk = signing_material
    mock_otl_client.aget_worker.return_value = {
        "personNumber": "10021",
        "fullName": "Employee Name",
        "isActive": True,
    }
    token = _oidc_token(private_key)
    env = {
        "OIDC_ISSUER": "https://identity.example.com",
        "OIDC_AUDIENCE": "otl-api",
        "OIDC_JWKS_URL": "https://identity.example.com/keys",
        "OIDC_PERSON_NUMBER_CLAIM": "identity.person_number",
        "AUTH_USERS": "",
    }
    _clear_oidc_caches()
    with (
        patch.dict(os.environ, env),
        patch(
            "backend.core.auth._fetch_json",
            new=AsyncMock(return_value={"keys": [public_jwk]}),
        ),
    ):
        response = client.post(
            "/api/auth/login",
            json={"username": "attacker", "password": token},
        )
    assert response.status_code == 200
    assert response.json()["employee"]["employeeId"] == "10021"
    assert mock_otl_client.aget_worker.await_args.args[1] == "10021"
    _clear_oidc_caches()


def test_csrf_and_session_rotation_with_active_state_revalidation(
    client, mock_otl_client, password_hash
):
    env = {
        "DEV_MODE": "true",
        "TEST_MODE": "false",
        "REDIS_REQUIRED": "false",
        "REDIS_URL": "",
        "ALLOW_IN_MEMORY_SESSIONS": "true",
        "SESSION_SECRET_KEY": "production-test-session-secret-key-48-bytes-long",
        "SESSION_COOKIE_SECURE": "false",
        "AUTH_USERS": json.dumps({"10021": password_hash}),
        "AUTH_PASSWORD": "",
        "OIDC_ISSUER": "",
        "OIDC_AUDIENCE": "",
    }
    mock_otl_client.aget_worker.return_value = {
        "personNumber": "10021",
        "fullName": "Employee Name",
        "isActive": True,
    }
    with patch.dict(os.environ, env):
        health = client.get("/api/health")
        login = client.post(
            "/api/auth/login",
            json={
                "username": "10021",
                "password": "correct horse battery staple",
            },
            headers={"X-CSRF-Token": health.headers["X-CSRF-Token"]},
        )
        assert login.status_code == 200
        old_session = client.cookies.get("otl_session")
        old_csrf = client.cookies.get("csrf_token")
        refreshed = client.post(
            "/api/auth/refresh",
            headers={"X-CSRF-Token": old_csrf},
        )
        assert refreshed.status_code == 200
        new_session = client.cookies.get("otl_session")
        new_csrf = client.cookies.get("csrf_token")
        assert new_session != old_session
        assert new_csrf != old_csrf

        stale_csrf = client.post(
            "/api/auth/refresh",
            headers={"X-CSRF-Token": old_csrf},
        )
        assert stale_csrf.status_code == 403

        client.cookies.set("otl_session", old_session)
        client.cookies.set("csrf_token", old_csrf)
        assert client.get("/api/auth/session").status_code == 401

        client.cookies.set("otl_session", new_session)
        client.cookies.set("csrf_token", new_csrf)
        assert client.get("/api/auth/session").status_code == 200

        mock_otl_client.aget_worker.return_value = {
            "personNumber": "10021",
            "fullName": "Employee Name",
            "isActive": False,
        }
        inactive_refresh = client.post(
            "/api/auth/refresh",
            headers={"X-CSRF-Token": new_csrf},
        )
        assert inactive_refresh.status_code == 401
        assert client.get("/api/auth/session").status_code == 200

        mock_otl_client.aget_worker.return_value = {
            "personNumber": "10021",
            "fullName": "Employee Name",
            "isActive": True,
        }
        logout = client.post("/api/auth/logout", headers={"X-CSRF-Token": new_csrf})
        assert logout.status_code == 200
        assert client.get("/api/auth/session").status_code == 401


@pytest.mark.asyncio
async def test_production_never_falls_back_when_redis_is_disabled():
    employee = auth.Employee(
        employee_id="10021", username="10021", full_name="Employee Name"
    )
    env = {
        "DEV_MODE": "false",
        "TEST_MODE": "false",
        "REDIS_REQUIRED": "false",
        "ALLOW_IN_MEMORY_SESSIONS": "true",
        "REDIS_URL": "",
        "SESSION_SECRET_KEY": "production-test-session-secret-key-48-bytes-long",
    }
    with patch.dict(os.environ, env):
        await auth._blocklist().clear_local()
        with pytest.raises(SessionStoreUnavailable):
            await auth.issue_session(employee)


@pytest.mark.asyncio
async def test_redis_errors_fail_closed_for_session_read_and_revocation():
    from backend.core.token_blocklist import _blocklist

    env = {
        "DEV_MODE": "false",
        "TEST_MODE": "false",
        "REDIS_REQUIRED": "true",
        "ALLOW_IN_MEMORY_SESSIONS": "true",
        "REDIS_URL": "redis://redis.example.com:6379/0",
    }
    blocklist = _blocklist()
    mock_redis = MagicMock()
    mock_redis.ping = AsyncMock(return_value=True)
    mock_redis.exists = AsyncMock(return_value=0)
    mock_redis.get = AsyncMock(side_effect=OSError("redis unavailable"))
    mock_redis.close = AsyncMock()
    pipeline = MagicMock()
    pipeline.setex.return_value = pipeline
    pipeline.delete.return_value = pipeline
    pipeline.execute = AsyncMock(side_effect=OSError("redis unavailable"))
    mock_redis.pipeline.return_value = pipeline

    with (
        patch.dict(os.environ, env, clear=False),
        patch("redis.asyncio.from_url", return_value=mock_redis),
    ):
        blocklist._redis = None
        blocklist._redis_url = None
        blocklist._last_reconnect = 0.0
        blocklist._backoff = 1.0
        with pytest.raises(SessionStoreUnavailable):
            await blocklist.get_session("missing-session")
        mock_redis.ping = AsyncMock(return_value=True)
        blocklist._redis = mock_redis
        blocklist._redis_url = env["REDIS_URL"]
        blocklist._last_reconnect = 0.0
        blocklist._backoff = 1.0
        with pytest.raises(SessionStoreUnavailable):
            await blocklist.revoke_session("session-id", 60)


@pytest.mark.asyncio
async def test_current_session_maps_redis_failure_to_503():
    unavailable = MagicMock()
    unavailable.get_session = AsyncMock(
        side_effect=SessionStoreUnavailable("unavailable")
    )
    payload = {
        "sub": "10021",
        "username": "10021",
        "jti": "session-id",
        "exp": 4_102_444_800,
    }
    with (
        patch("backend.core.auth._decode_session_token", return_value=payload),
        patch("backend.core.auth._blocklist", return_value=unavailable),
        pytest.raises(HTTPException) as exc,
    ):
        await auth.current_session(otl_session="opaque-session-token")
    assert exc.value.status_code == 503
    assert exc.value.detail == "Session validation is temporarily unavailable."
