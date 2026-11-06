import asyncio
import base64
import os
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from backend.core import auth
from backend.core.auth import (
    AuthenticationConfigurationError,
    AuthenticationError,
    _b64decode,
    _b64encode,
    _CachedJwks,
    _clear_oidc_caches,
    _credential_verifier,
    _decode_session_token,
    _fetch_json,
    _float_env,
    _is_insecure_placeholder,
    _jwt_secret,
    _oidc_discovery_cache_seconds,
    _oidc_refresh_minimum_seconds,
    _parse_auth_users,
    _reject_duplicate_json_keys,
    _session_cookie_name,
    _session_samesite,
    _ttl_seconds,
    activate_session,
    constant_time_equals,
    hash_scrypt_password,
)


def _make_rsa_token(private_key, claims, kid="test-key"):
    return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": kid})


def test_verify_empty_credential():
    verifier = auth.OidcTokenVerifier(
        issuer="https://example.com",
        audience="api",
        algorithms=("RS256",),
        person_number_claim="sub",
        username_claim="preferred_username",
    )
    result = asyncio.run(verifier.verify("user", ""))
    assert result is None


def test_verify_credential_too_long():
    verifier = auth.OidcTokenVerifier(
        issuer="https://example.com",
        audience="api",
        algorithms=("RS256",),
        person_number_claim="sub",
        username_claim="preferred_username",
    )
    result = asyncio.run(verifier.verify("user", "x" * 32769))
    assert result is None


def test_verify_invalid_jwt_header():
    verifier = auth.OidcTokenVerifier(
        issuer="https://example.com",
        audience="api",
        algorithms=("RS256",),
        person_number_claim="sub",
        username_claim="preferred_username",
    )
    result = asyncio.run(verifier.verify("user", "not-a-jwt"))
    assert result is None


def test_verify_unsupported_algorithm():
    verifier = auth.OidcTokenVerifier(
        issuer="https://example.com",
        audience="api",
        algorithms=("RS256",),
        person_number_claim="sub",
        username_claim="preferred_username",
    )
    token = jwt.encode(
        {"sub": "123", "iss": "https://example.com", "aud": "api", "exp": 9999999999},
        "secret",
        algorithm="HS256",
        headers={"kid": "test-key"},
    )
    result = asyncio.run(verifier.verify("user", token))
    assert result is None


def test_verify_kid_not_in_jwks():
    verifier = auth.OidcTokenVerifier(
        issuer="https://example.com",
        audience="api",
        algorithms=("RS256",),
        person_number_claim="sub",
        username_claim="preferred_username",
    )
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = _make_rsa_token(
        private_key,
        {"sub": "123", "iss": "https://example.com", "aud": "api", "exp": 9999999999},
        kid="unknown-key",
    )
    with patch.object(
        verifier,
        "_get_jwks",
        new=AsyncMock(
            return_value=_CachedJwks(keys={}, expires_at=9999999999, fetched_at=0)
        ),
    ):
        result = asyncio.run(verifier.verify("user", token))
    assert result is None


def test_verify_jwk_kty_oct_or_none():
    verifier = auth.OidcTokenVerifier(
        issuer="https://example.com",
        audience="api",
        algorithms=("RS256",),
        person_number_claim="sub",
        username_claim="preferred_username",
    )
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = _make_rsa_token(
        private_key,
        {"sub": "123", "iss": "https://example.com", "aud": "api", "exp": 9999999999},
        kid="test-key",
    )
    jwks = _CachedJwks(
        keys={"test-key": {"kty": "oct", "alg": "RS256"}},
        expires_at=9999999999,
        fetched_at=0,
    )
    with patch.object(verifier, "_get_jwks", new=AsyncMock(return_value=jwks)):
        result = asyncio.run(verifier.verify("user", token))
    assert result is None


def test_verify_declared_algorithm_mismatch():
    verifier = auth.OidcTokenVerifier(
        issuer="https://example.com",
        audience="api",
        algorithms=("RS256",),
        person_number_claim="sub",
        username_claim="preferred_username",
    )
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = _make_rsa_token(
        private_key,
        {"sub": "123", "iss": "https://example.com", "aud": "api", "exp": 9999999999},
        kid="test-key",
    )
    jwks = _CachedJwks(
        keys={"test-key": {"kty": "RSA", "alg": "ES256"}},
        expires_at=9999999999,
        fetched_at=0,
    )
    with patch.object(verifier, "_get_jwks", new=AsyncMock(return_value=jwks)):
        result = asyncio.run(verifier.verify("user", token))
    assert result is None


def test_verify_declared_use_not_sig():
    verifier = auth.OidcTokenVerifier(
        issuer="https://example.com",
        audience="api",
        algorithms=("RS256",),
        person_number_claim="sub",
        username_claim="preferred_username",
    )
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = _make_rsa_token(
        private_key,
        {"sub": "123", "iss": "https://example.com", "aud": "api", "exp": 9999999999},
        kid="test-key",
    )
    jwks = _CachedJwks(
        keys={"test-key": {"kty": "RSA", "alg": "RS256", "use": "enc"}},
        expires_at=9999999999,
        fetched_at=0,
    )
    with patch.object(verifier, "_get_jwks", new=AsyncMock(return_value=jwks)):
        result = asyncio.run(verifier.verify("user", token))
    assert result is None


def test_verify_employee_id_too_short():
    verifier = auth.OidcTokenVerifier(
        issuer="https://example.com",
        audience="api",
        algorithms=("RS256",),
        person_number_claim="sub",
        username_claim="preferred_username",
    )
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = _make_rsa_token(
        private_key,
        {"sub": "", "iss": "https://example.com", "aud": "api", "exp": 9999999999},
        kid="test-key",
    )
    jwks = _CachedJwks(
        keys={"test-key": {"kty": "RSA", "alg": "RS256"}},
        expires_at=9999999999,
        fetched_at=0,
    )
    with patch.object(verifier, "_get_jwks", new=AsyncMock(return_value=jwks)):
        result = asyncio.run(verifier.verify("user", token))
    assert result is None


def test_verify_employee_id_too_long():
    verifier = auth.OidcTokenVerifier(
        issuer="https://example.com",
        audience="api",
        algorithms=("RS256",),
        person_number_claim="sub",
        username_claim="preferred_username",
    )
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = _make_rsa_token(
        private_key,
        {
            "sub": "x" * 129,
            "iss": "https://example.com",
            "aud": "api",
            "exp": 9999999999,
        },
        kid="test-key",
    )
    jwks = _CachedJwks(
        keys={"test-key": {"kty": "RSA", "alg": "RS256"}},
        expires_at=9999999999,
        fetched_at=0,
    )
    with patch.object(verifier, "_get_jwks", new=AsyncMock(return_value=jwks)):
        result = asyncio.run(verifier.verify("user", token))
    assert result is None


def test_verify_username_too_long():
    """Cover OIDC verify: username > 256 chars falls back to employee_id."""
    import asyncio

    verifier = auth.OidcTokenVerifier(
        issuer="https://example.com",
        audience="api",
        algorithms=("RS256",),
        person_number_claim="sub",
        username_claim="preferred_username",
    )
    # Mock the entire JWT verification chain
    with patch(
        "jwt.get_unverified_header", return_value={"alg": "RS256", "kid": "test-key"}
    ):
        with patch.object(
            verifier,
            "_get_jwks",
            new=AsyncMock(
                return_value=_CachedJwks(
                    keys={"test-key": {"kty": "RSA", "alg": "RS256", "use": "sig"}},
                    expires_at=9999999999,
                    fetched_at=0,
                )
            ),
        ):
            # Mock PyJWK.from_dict to avoid RSA key parsing
            mock_signing_key = MagicMock()
            mock_signing_key.key = "fake-key"
            with patch("jwt.PyJWK.from_dict", return_value=mock_signing_key):
                # Mock jwt.decode to return payload with long username
                with patch(
                    "jwt.decode",
                    return_value={"sub": "123", "preferred_username": "x" * 257},
                ):
                    result = asyncio.run(verifier.verify("user", "fake-token"))
    assert result is not None
    assert result.employee_id == "123"
    assert result.username == "123"


def test_verify_jwt_decode_error():
    verifier = auth.OidcTokenVerifier(
        issuer="https://example.com",
        audience="api",
        algorithms=("RS256",),
        person_number_claim="sub",
        username_claim="preferred_username",
    )
    token = jwt.encode(
        {"sub": "123", "iss": "https://example.com", "aud": "api", "exp": 1},
        "secret",
        algorithm="HS256",
        headers={"kid": "test-key"},
    )
    jwks = _CachedJwks(
        keys={"test-key": {"kty": "RSA", "alg": "HS256"}},
        expires_at=9999999999,
        fetched_at=0,
    )
    with patch.object(verifier, "_get_jwks", new=AsyncMock(return_value=jwks)):
        result = asyncio.run(verifier.verify("user", token))
    assert result is None


def test_get_jwks_force_within_refresh_minimum():
    verifier = auth.OidcTokenVerifier(
        issuer="https://example.com",
        audience="api",
        algorithms=("RS256",),
        person_number_claim="sub",
        username_claim="preferred_username",
    )
    cache_key = ("https://example.com", "")
    auth._JWKS_CACHE[cache_key] = _CachedJwks(
        keys={}, expires_at=9999999999, fetched_at=time.monotonic()
    )
    try:
        with pytest.raises(AuthenticationError, match="Invalid OIDC token"):
            asyncio.run(verifier._get_jwks(force=True))
    finally:
        del auth._JWKS_CACHE[cache_key]


def test_fetch_json_http_error():
    with patch("httpx.AsyncClient") as mock_client:
        mock_instance = AsyncMock()
        mock_instance.get = AsyncMock(side_effect=httpx.HTTPError("boom"))
        mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
        with pytest.raises(httpx.HTTPError):
            asyncio.run(_fetch_json("https://example.com/keys"))


def test_fetch_json_non_dict_response():
    with patch("httpx.AsyncClient") as mock_client:
        mock_response = MagicMock()
        mock_response.json.return_value = ["not", "a", "dict"]
        mock_response.raise_for_status = MagicMock()
        mock_instance = AsyncMock()
        mock_instance.get = AsyncMock(return_value=mock_response)
        mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
        with pytest.raises(TypeError, match="not an object"):
            asyncio.run(_fetch_json("https://example.com/keys"))


def test_parse_auth_users_empty_document():
    with pytest.raises(AuthenticationConfigurationError, match="at least one user"):
        _parse_auth_users("{}")
    _clear_oidc_caches()


def test_parse_auth_users_too_many():
    raw = "{" + ",".join(f'"u{i}":"h{i}"' for i in range(10001)) + "}"
    with pytest.raises(AuthenticationConfigurationError, match="too many users"):
        _parse_auth_users(raw)
    _clear_oidc_caches()


def test_parse_auth_users_user_object_not_str_or_dict():
    raw = '{"123": [1,2,3]}'
    with pytest.raises(
        AuthenticationConfigurationError, match="scrypt strings or user objects"
    ):
        _parse_auth_users(raw)
    _clear_oidc_caches()


def test_parse_auth_users_employee_id_bool():
    raw = '{"123": {"employeeId": true, "username": "u", "password": "hash"}}'
    with pytest.raises(
        AuthenticationConfigurationError,
        match="employeeId values must be strings or integers",
    ):
        _parse_auth_users(raw)
    _clear_oidc_caches()


def test_parse_auth_users_username_not_str():
    raw = '{"123": {"username": 123, "password": "hash"}}'
    with pytest.raises(
        AuthenticationConfigurationError, match="username values must be strings"
    ):
        _parse_auth_users(raw)
    _clear_oidc_caches()


def test_parse_auth_users_password_not_str():
    raw = '{"123": {"password": 123}}'
    with pytest.raises(
        AuthenticationConfigurationError, match="password values must be scrypt strings"
    ):
        _parse_auth_users(raw)
    _clear_oidc_caches()


def test_parse_auth_users_incomplete_user():
    raw = '{"123": {"employeeId": "", "username": "", "password": ""}}'
    with pytest.raises(AuthenticationConfigurationError, match="incomplete user"):
        _parse_auth_users(raw)
    _clear_oidc_caches()


def test_reject_duplicate_json_keys():
    with pytest.raises(ValueError, match="duplicate JSON key"):
        _reject_duplicate_json_keys([("a", 1), ("a", 2)])


def test_b64decode_empty_value():
    with pytest.raises(ValueError, match="invalid base64 value"):
        _b64decode("")


def test_b64decode_too_long():
    with pytest.raises(ValueError, match="invalid base64 value"):
        _b64decode("x" * 257)


def test_b64decode_invalid_chars():
    with pytest.raises(ValueError, match="invalid base64 value"):
        _b64decode("!!!not-base64!!!")


def test_validate_scrypt_parameters_invalid_n():
    with pytest.raises(ValueError, match="unsupported scrypt parameters"):
        auth._validate_scrypt_parameters(1000, 8, 1)


def test_validate_scrypt_parameters_invalid_r():
    with pytest.raises(ValueError, match="unsupported scrypt parameters"):
        auth._validate_scrypt_parameters(16384, 0, 1)


def test_validate_scrypt_parameters_invalid_p():
    with pytest.raises(ValueError, match="unsupported scrypt parameters"):
        auth._validate_scrypt_parameters(16384, 8, 0)


def test_validate_scrypt_parameters_memory():
    with pytest.raises(ValueError, match="unsupported scrypt parameters"):
        auth._validate_scrypt_parameters(1048576, 16, 8)


def test_hash_scrypt_password_empty():
    with pytest.raises(ValueError, match="password length"):
        hash_scrypt_password("")


def test_hash_scrypt_password_too_long():
    with pytest.raises(ValueError, match="password length"):
        hash_scrypt_password("x" * 1025)


def test_parse_password_hash_invalid_format():
    with pytest.raises(ValueError, match="invalid scrypt password hash"):
        auth._parse_password_hash("not-scrypt")


def test_parse_password_hash_wrong_parts():
    with pytest.raises(ValueError, match="invalid scrypt password hash"):
        auth._parse_password_hash("scrypt$1$2$3")


def test_parse_password_hash_bad_params():
    with pytest.raises(ValueError, match="invalid scrypt password hash"):
        auth._parse_password_hash("scrypt$abc$8$1$salt$digest")


def test_parse_password_hash_short_salt():
    short_salt = base64.urlsafe_b64encode(b"short").decode("ascii")
    short_digest = base64.urlsafe_b64encode(b"0" * 32).decode("ascii")
    with pytest.raises(ValueError, match="invalid scrypt password hash"):
        auth._parse_password_hash(f"scrypt$16384$8$1${short_salt}${short_digest}")


def test_parse_password_hash_wrong_digest_len():
    salt = base64.urlsafe_b64encode(b"0" * 16).decode("ascii")
    bad_digest = base64.urlsafe_b64encode(b"0" * 10).decode("ascii")
    with pytest.raises(ValueError, match="invalid scrypt password hash"):
        auth._parse_password_hash(f"scrypt$16384$8$1${salt}${bad_digest}")


def test_verify_scrypt_empty_password():
    salt = base64.urlsafe_b64encode(b"0" * 16).decode("ascii")
    digest = base64.urlsafe_b64encode(b"0" * 32).decode("ascii")
    pw_hash = auth._PasswordHash(
        n=16384,
        r=8,
        p=1,
        salt=base64.urlsafe_b64decode(salt),
        digest=base64.urlsafe_b64decode(digest),
    )
    assert auth._verify_scrypt("", pw_hash) is False


def test_verify_scrypt_too_long_password():
    salt = base64.urlsafe_b64encode(b"0" * 16).decode("ascii")
    digest = base64.urlsafe_b64encode(b"0" * 32).decode("ascii")
    pw_hash = auth._PasswordHash(
        n=16384,
        r=8,
        p=1,
        salt=base64.urlsafe_b64decode(salt),
        digest=base64.urlsafe_b64decode(digest),
    )
    assert auth._verify_scrypt("x" * 1025, pw_hash) is False


def test_credential_verifier_demo_mode():
    with patch.dict(os.environ, {"DEMO_MODE": "true"}):
        verifier = _credential_verifier()
        from backend.core.auth import DemoCredentialVerifier

        assert isinstance(verifier, DemoCredentialVerifier)


def test_credential_verifier_oidc_missing_audience():
    with patch.dict(
        os.environ, {"OIDC_ISSUER": "https://example.com", "OIDC_AUDIENCE": ""}
    ):
        with pytest.raises(
            AuthenticationConfigurationError, match="must be configured together"
        ):
            _credential_verifier()


def test_credential_verifier_no_auth_configured():
    with patch.dict(
        os.environ,
        {"OIDC_ISSUER": "", "OIDC_AUDIENCE": "", "AUTH_USERS": "", "AUTH_PASSWORD": ""},
        clear=False,
    ):
        os.environ.pop("DEV_MODE", None)
        os.environ.pop("TEST_MODE", None)
        try:
            with pytest.raises(
                AuthenticationConfigurationError,
                match="Authentication is not configured",
            ):
                _credential_verifier()
        finally:
            os.environ["DEV_MODE"] = "true"
            os.environ["TEST_MODE"] = "true"


def test_credential_verifier_legacy_password_insecure_placeholder():
    with patch.dict(
        os.environ,
        {
            "AUTH_PASSWORD": "replace-with-real-password",
            "DEV_MODE": "true",
            "TEST_MODE": "true",
        },
    ):
        with pytest.raises(AuthenticationConfigurationError, match="not configured"):
            _credential_verifier()


def test_is_insecure_placeholder_none():
    assert _is_insecure_placeholder(None) is True


def test_is_insecure_placeholder_empty():
    assert _is_insecure_placeholder("") is True


def test_is_insecure_placeholder_match():
    assert _is_insecure_placeholder("replace-with-me") is True
    assert _is_insecure_placeholder("generate_a_secure_one") is True
    assert _is_insecure_placeholder("your_secure_password") is True
    assert _is_insecure_placeholder("your-password") is True
    assert _is_insecure_placeholder("change-me") is True
    assert _is_insecure_placeholder("changeme") is True


def test_is_insecure_placeholder_no_match():
    assert _is_insecure_placeholder("real-secret-12345") is False


def test_jwt_secret_production_too_short():
    with patch.dict(
        os.environ,
        {"SESSION_SECRET_KEY": "short", "DEV_MODE": "false", "TEST_MODE": "false"},
        clear=False,
    ):
        auth._fallback_jwt_secret = None
        with pytest.raises(RuntimeError, match="at least 32 bytes"):
            _jwt_secret()


def test_jwt_secret_production_missing():
    with patch.dict(
        os.environ,
        {"SESSION_SECRET_KEY": "", "DEV_MODE": "false", "TEST_MODE": "false"},
        clear=False,
    ):
        auth._fallback_jwt_secret = None
        with pytest.raises(RuntimeError, match="required outside development"):
            _jwt_secret()


def test_jwt_secret_development_fallback():
    with patch.dict(
        os.environ, {"SESSION_SECRET_KEY": "", "DEV_MODE": "true", "TEST_MODE": "true"}
    ):
        auth._fallback_jwt_secret = None
        secret = _jwt_secret()
        assert secret is not None
        assert len(secret) > 0


def test_session_ttl_invalid():
    with patch.dict(os.environ, {"SESSION_TTL_SECONDS": "not-a-number"}):
        with pytest.raises(RuntimeError, match="must be an integer"):
            _ttl_seconds()


def test_cookie_secure_default_true():
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("SESSION_COOKIE_SECURE", None)
        assert auth.cookie_secure() is True


def test_session_cookie_name_secure():
    with patch.dict(os.environ, {"SESSION_COOKIE_SECURE": "true"}):
        name = _session_cookie_name()
        assert name == "__Host-otl_session"


def test_session_cookie_name_insecure():
    with patch.dict(os.environ, {"SESSION_COOKIE_SECURE": "false"}):
        name = _session_cookie_name()
        assert name == "otl_session"


def test_session_samesite_none_requires_secure():
    with patch.dict(
        os.environ,
        {"SESSION_COOKIE_SAMESITE": "none", "SESSION_COOKIE_SECURE": "false"},
    ):
        with pytest.raises(RuntimeError, match="requires SESSION_COOKIE_SECURE=true"):
            _session_samesite()


def test_session_samesite_invalid():
    with patch.dict(os.environ, {"SESSION_COOKIE_SAMESITE": "invalid"}):
        assert _session_samesite() == "strict"


def test_decode_session_token_invalid_sub():
    token = jwt.encode(
        {
            "sub": 123,
            "username": "user",
            "iss": "otl-voice",
            "aud": "otl-voice-web",
            "iat": 1,
            "exp": 9999999999,
            "jti": "abc",
        },
        _jwt_secret(),
        algorithm="HS256",
    )
    with pytest.raises(AuthenticationError, match="Invalid session token"):
        _decode_session_token(token)


def test_decode_session_token_invalid_exp_bool():
    token = jwt.encode(
        {
            "sub": "user",
            "username": "user",
            "iss": "otl-voice",
            "aud": "otl-voice-web",
            "iat": 1,
            "exp": True,
            "jti": "abc",
        },
        _jwt_secret(),
        algorithm="HS256",
    )
    with pytest.raises(AuthenticationError, match="Invalid session token"):
        _decode_session_token(token)


def test_decode_session_token_invalid_exp_type():
    token = jwt.encode(
        {
            "sub": "user",
            "username": "user",
            "iss": "otl-voice",
            "aud": "otl-voice-web",
            "iat": 1,
            "exp": "not-a-number",
            "jti": "abc",
        },
        _jwt_secret(),
        algorithm="HS256",
    )
    with pytest.raises(AuthenticationError, match="Invalid session token"):
        _decode_session_token(token)


def test_activate_session_invalid_token():
    employee = MagicMock()
    employee.employee_id = "123"
    employee.username = "user"
    with pytest.raises(RuntimeError, match="Refusing to activate"):
        asyncio.run(activate_session("not-a-jwt", employee))


def test_activate_session_identity_mismatch():
    employee = MagicMock()
    employee.employee_id = "456"
    employee.username = "other"
    token = jwt.encode(
        {
            "sub": "123",
            "username": "user",
            "iss": "otl-voice",
            "aud": "otl-voice-web",
            "iat": 1,
            "exp": 9999999999,
            "jti": "abc",
        },
        _jwt_secret(),
        algorithm="HS256",
    )
    with pytest.raises(RuntimeError, match="does not match"):
        asyncio.run(activate_session(token, employee))


def test_float_env_invalid():
    with patch.dict(os.environ, {"OIDC_JWKS_CACHE_SECONDS": "not-a-number"}):
        with pytest.raises(AuthenticationConfigurationError, match="must be numeric"):
            _float_env("OIDC_JWKS_CACHE_SECONDS", 300.0)


def test_oidc_cache_functions():
    assert _oidc_discovery_cache_seconds() >= 30.0
    assert _oidc_discovery_cache_seconds() <= 3600.0
    assert _oidc_refresh_minimum_seconds() >= 1.0
    assert _oidc_refresh_minimum_seconds() <= 300.0


def test_constant_time_equals_surrogatepass():
    assert constant_time_equals("caf\u00e9", "caf\u00e9") is True
    assert constant_time_equals("caf\u00e9", "cafe") is False


def test_b64encode_decode_roundtrip():
    original = b"hello world"
    encoded = _b64encode(original)
    decoded = _b64decode(encoded)
    assert decoded == original
