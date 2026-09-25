from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from dataclasses import dataclass
from threading import Lock
from typing import Any, Literal, Protocol, cast
from urllib.parse import urlsplit

import httpx
import jwt
from fastapi import Cookie, HTTPException, Request, Response, status

from ..models import Employee
from .config import is_dev_mode, is_development_or_test, is_test_mode
from .limiter import set_authenticated_ws_identity
from .token_blocklist import SessionStoreUnavailable, StoredSession, _blocklist

logger = logging.getLogger(__name__)

SESSION_COOKIE_NAME = "otl_session"
JWT_ALGORITHM = "HS256"
SESSION_TOKEN_ISSUER = "otl-voice"
SESSION_TOKEN_AUDIENCE = "otl-voice-web"
_OIDC_ASYMMETRIC_ALGORITHMS = {
    "RS256",
    "RS384",
    "RS512",
    "PS256",
    "PS384",
    "PS512",
    "ES256",
    "ES384",
    "ES512",
    "EdDSA",
}
_SCRYPT_DEFAULT_N = 32768
_SCRYPT_DEFAULT_R = 8
_SCRYPT_DEFAULT_P = 1
_SCRYPT_SALT_BYTES = 16
_SCRYPT_HASH_BYTES = 32
_SCRYPT_MAX_MEMORY = 256 * 1024 * 1024
_DUMMY_PASSWORD_HASH = (
    "scrypt$32768$8$1$AAAAAAAAAAAAAAAAAAAAAA=="
    "$AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
)


class AuthenticationConfigurationError(RuntimeError):
    pass


class AuthenticationError(RuntimeError):
    pass


class IdentityProviderUnavailable(AuthenticationError):
    pass


@dataclass(frozen=True)
class AuthVerification:
    employee_id: str
    username: str


@dataclass(frozen=True)
class AuthUser:
    employee_id: str
    username: str
    password_hash: str


@dataclass(frozen=True)
class _PasswordHash:
    n: int
    r: int
    p: int
    salt: bytes
    digest: bytes


@dataclass
class _CachedJwks:
    keys: dict[str, dict[str, Any]]
    expires_at: float
    fetched_at: float


class CredentialVerifier(Protocol):
    async def verify(
        self, identifier: str, credential: str
    ) -> AuthVerification | None: ...


class LocalCredentialVerifier:
    def __init__(self, users: dict[str, AuthUser]) -> None:
        self._users = users
        self._dummy_hash = _parse_password_hash(_DUMMY_PASSWORD_HASH)

    async def verify(self, identifier: str, credential: str) -> AuthVerification | None:
        normalized_identifier = identifier.strip().casefold()
        user = self._users.get(normalized_identifier)
        parsed_hash = (
            _parse_password_hash(user.password_hash) if user else self._dummy_hash
        )
        matches = _verify_scrypt(credential, parsed_hash)
        if user is None or not matches:
            return None
        return AuthVerification(employee_id=user.employee_id, username=user.username)

    @classmethod
    def from_mapping(cls, raw_mapping: str) -> LocalCredentialVerifier:
        users = _parse_auth_users(raw_mapping)
        try:
            for user in users.values():
                _parse_password_hash(user.password_hash)
        except ValueError as exc:
            raise AuthenticationConfigurationError(
                "AUTH_USERS contains an invalid scrypt credential."
            ) from exc
        return cls(users)


class LegacyDevelopmentVerifier:
    def __init__(self, password: str) -> None:
        self._password = password

    async def verify(self, identifier: str, credential: str) -> AuthVerification | None:
        normalized_identifier = identifier.strip()
        if not normalized_identifier or not hmac.compare_digest(
            credential, self._password
        ):
            return None
        return AuthVerification(
            employee_id=normalized_identifier, username=normalized_identifier
        )


class OidcTokenVerifier:
    def __init__(
        self,
        issuer: str,
        audience: str,
        algorithms: tuple[str, ...],
        person_number_claim: str,
        username_claim: str,
    ) -> None:
        self._issuer = issuer
        self._audience = audience
        self._algorithms = algorithms
        self._person_number_claim = person_number_claim
        self._username_claim = username_claim

    async def verify(self, identifier: str, credential: str) -> AuthVerification | None:
        del identifier
        if not credential or len(credential) > 32768:
            return None
        try:
            try:
                header = jwt.get_unverified_header(credential)
            except jwt.PyJWTError:
                return None
            algorithm = header.get("alg")
            key_id = header.get("kid")
            if (
                not isinstance(algorithm, str)
                or algorithm not in self._algorithms
                or not isinstance(key_id, str)
                or not key_id
            ):
                return None
            jwks = await self._get_jwks()
            jwk = jwks.keys.get(key_id)
            if jwk is None:
                jwks = await self._get_jwks(force=True)
                jwk = jwks.keys.get(key_id)
            if jwk is None or jwk.get("kty") in {"oct", "none"}:
                return None
            declared_algorithm = jwk.get("alg")
            if declared_algorithm is not None and declared_algorithm != algorithm:
                return None
            declared_use = jwk.get("use")
            if declared_use is not None and declared_use != "sig":
                return None
            try:
                signing_key = jwt.PyJWK.from_dict(jwk, algorithm=algorithm).key
                payload = jwt.decode(
                    credential,
                    key=signing_key,
                    algorithms=list(self._algorithms),
                    audience=self._audience,
                    issuer=self._issuer,
                    options={
                        "require": ["exp", "iat", "iss", "aud", "sub"],
                        "verify_signature": True,
                        "verify_exp": True,
                        "verify_iat": True,
                        "verify_iss": True,
                        "verify_aud": True,
                    },
                )
            except (jwt.PyJWTError, TypeError, ValueError, KeyError):
                return None
            employee_id = _read_claim(payload, self._person_number_claim)
            username = _read_claim(payload, self._username_claim)
            if employee_id is None:
                return None
            if not 1 <= len(employee_id) <= 128:
                return None
            if username is None or not 1 <= len(username) <= 256:
                username = employee_id
            return AuthVerification(employee_id=employee_id, username=username)
        except IdentityProviderUnavailable:
            raise
        except AuthenticationError:
            raise
        except Exception:
            raise IdentityProviderUnavailable(
                "The OIDC token verifier is temporarily unavailable."
            ) from None

    async def _get_jwks(self, force: bool = False) -> _CachedJwks:
        cache_key = (self._issuer, self._configured_jwks_url())
        cached = _JWKS_CACHE.get(cache_key)
        now = time.monotonic()
        if cached is not None and not force and cached.expires_at > now:
            return cached
        if (
            force
            and cached is not None
            and now - cached.fetched_at < _oidc_refresh_minimum_seconds()
        ):
            raise AuthenticationError("Invalid OIDC token.")
        async with _JWKS_LOCK:
            cached = _JWKS_CACHE.get(cache_key)
            now = time.monotonic()
            if cached is not None and not force and cached.expires_at > now:
                return cached
            jwks_url = await self._jwks_url()
            try:
                document = await _fetch_json(jwks_url)
            except httpx.HTTPError as exc:
                raise IdentityProviderUnavailable(
                    "The OIDC signing keys are temporarily unavailable."
                ) from exc
            if not isinstance(document, dict) or not isinstance(
                document.get("keys"), list
            ):
                raise IdentityProviderUnavailable(
                    "The OIDC signing-key document is invalid."
                )
            keys: dict[str, dict[str, Any]] = {}
            for raw_key in document["keys"]:
                if not isinstance(raw_key, dict):
                    continue
                key_id = raw_key.get("kid")
                if isinstance(key_id, str) and key_id and key_id not in keys:
                    keys[key_id] = raw_key
            if not keys:
                raise IdentityProviderUnavailable(
                    "The OIDC signing-key document contains no usable keys."
                )
            refreshed = _CachedJwks(
                keys=keys,
                expires_at=now + _oidjwks_cache_seconds(),
                fetched_at=now,
            )
            _JWKS_CACHE[cache_key] = refreshed
            return refreshed

    def _configured_jwks_url(self) -> str:
        return os.getenv("OIDC_JWKS_URL", "").strip()

    async def _jwks_url(self) -> str:
        configured = self._configured_jwks_url()
        if configured:
            _validate_oidc_endpoint(configured, "OIDC_JWKS_URL")
            return configured
        cache_key = self._issuer
        cached = _DISCOVERY_CACHE.get(cache_key)
        now = time.monotonic()
        if cached is not None and cached[0] > now:
            return cached[1]
        async with _DISCOVERY_LOCK:
            cached = _DISCOVERY_CACHE.get(cache_key)
            now = time.monotonic()
            if cached is not None and cached[0] > now:
                return cached[1]
            discovery_url = (
                self._issuer.rstrip("/") + "/.well-known/openid-configuration"
            )
            _validate_oidc_endpoint(discovery_url, "OIDC_ISSUER")
            try:
                document = await _fetch_json(discovery_url)
            except httpx.HTTPError as exc:
                raise IdentityProviderUnavailable(
                    "OIDC provider metadata is temporarily unavailable."
                ) from exc
            if not isinstance(document, dict):
                raise IdentityProviderUnavailable("OIDC provider metadata is invalid.")
            discovered_issuer = document.get("issuer")
            jwks_url = document.get("jwks_uri")
            if discovered_issuer != self._issuer or not isinstance(jwks_url, str):
                raise IdentityProviderUnavailable(
                    "OIDC provider metadata failed issuer or key-URL validation."
                )
            _validate_oidc_endpoint(jwks_url, "OIDC jwks_uri")
            _DISCOVERY_CACHE[cache_key] = (
                now + _oidc_discovery_cache_seconds(),
                jwks_url,
            )
            return jwks_url


_JWKS_CACHE: dict[tuple[str, str], _CachedJwks] = {}
_DISCOVERY_CACHE: dict[str, tuple[float, str]] = {}
_JWKS_LOCK = asyncio.Lock()
_DISCOVERY_LOCK = asyncio.Lock()


async def _fetch_json(url: str) -> dict[str, Any]:
    timeout_seconds = max(1.0, min(30.0, _float_env("OIDC_HTTP_TIMEOUT_SECONDS", 5.0)))
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(timeout_seconds), follow_redirects=False
    ) as client:
        response = await client.get(url, headers={"Accept": "application/json"})
        response.raise_for_status()
    document = response.json()
    if not isinstance(document, dict):
        raise TypeError("OIDC response is not an object")
    return document


def _validate_oidc_endpoint(url: str, setting_name: str) -> None:
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"https", "http"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise AuthenticationConfigurationError(
            f"{setting_name} must be an absolute HTTP(S) URL without credentials."
        )
    if parsed.scheme != "https" and not is_development_or_test():
        raise AuthenticationConfigurationError(
            f"{setting_name} must use HTTPS outside development and test."
        )


def _read_claim(payload: dict[str, Any], claim_path: str) -> str | None:
    value: Any = payload
    for component in claim_path.split("."):
        if not component or not isinstance(value, dict) or component not in value:
            return None
        value = value[component]
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    normalized = str(value).strip()
    return normalized or None


def _oidc_algorithms() -> tuple[str, ...]:
    raw = os.getenv("OIDC_ALGORITHMS", "RS256")
    algorithms = tuple(
        dict.fromkeys(
            algorithm.strip() for algorithm in raw.split(",") if algorithm.strip()
        )
    )
    if not algorithms or any(
        algorithm not in _OIDC_ASYMMETRIC_ALGORITHMS for algorithm in algorithms
    ):
        raise AuthenticationConfigurationError(
            "OIDC_ALGORITHMS must contain only supported asymmetric signing algorithms."
        )
    return algorithms


def _parse_auth_users(raw_mapping: str) -> dict[str, AuthUser]:
    try:
        document = json.loads(
            raw_mapping, object_pairs_hook=_reject_duplicate_json_keys
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise AuthenticationConfigurationError(
            "AUTH_USERS must be a valid JSON object."
        ) from exc
    if not isinstance(document, dict) or not document:
        raise AuthenticationConfigurationError(
            "AUTH_USERS must contain at least one user."
        )
    if len(document) > 10000:
        raise AuthenticationConfigurationError("AUTH_USERS contains too many users.")
    users: dict[str, AuthUser] = {}
    for raw_identifier, raw_user in document.items():
        if not isinstance(raw_identifier, str) or not raw_identifier.strip():
            raise AuthenticationConfigurationError(
                "Every AUTH_USERS key must be a non-empty username or person number."
            )
        identifier = raw_identifier.strip()
        if isinstance(raw_user, str):
            employee_id = identifier
            username = identifier
            password_hash = raw_user
        elif isinstance(raw_user, dict):
            employee_id_value = raw_user.get("employeeId", identifier)
            username_value = raw_user.get("username", identifier)
            password_hash_value = raw_user.get("password")
            if not isinstance(employee_id_value, (str, int)) or isinstance(
                employee_id_value, bool
            ):
                raise AuthenticationConfigurationError(
                    "AUTH_USERS employeeId values must be strings or integers."
                )
            if not isinstance(username_value, str):
                raise AuthenticationConfigurationError(
                    "AUTH_USERS username values must be strings."
                )
            employee_id = str(employee_id_value).strip()
            username = username_value.strip()
            if not isinstance(password_hash_value, str):
                raise AuthenticationConfigurationError(
                    "AUTH_USERS password values must be scrypt strings."
                )
            password_hash = password_hash_value
        else:
            raise AuthenticationConfigurationError(
                "AUTH_USERS values must be scrypt strings or user objects."
            )
        if not employee_id or not username or not password_hash.strip():
            raise AuthenticationConfigurationError(
                "AUTH_USERS contains an incomplete user."
            )
        normalized_identifier = identifier.casefold()
        if normalized_identifier in users:
            raise AuthenticationConfigurationError(
                "AUTH_USERS contains duplicate case-insensitive identifiers."
            )
        users[normalized_identifier] = AuthUser(
            employee_id=employee_id,
            username=username,
            password_hash=password_hash.strip(),
        )
    return users


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii")


def _b64decode(value: str) -> bytes:
    if not value or len(value) > 256:
        raise ValueError("invalid base64 value")
    try:
        return base64.b64decode(value.encode("ascii"), altchars=b"-_", validate=True)
    except (binascii.Error, UnicodeEncodeError) as exc:
        raise ValueError("invalid base64 value") from exc


def _validate_scrypt_parameters(n: int, r: int, p: int) -> None:
    if (
        n < 16384
        or n > 1048576
        or n & (n - 1)
        or r < 1
        or r > 16
        or p < 1
        or p > 8
        or 128 * n * r > _SCRYPT_MAX_MEMORY
    ):
        raise ValueError("unsupported scrypt parameters")


def hash_scrypt_password(
    password: str,
    *,
    n: int = _SCRYPT_DEFAULT_N,
    r: int = _SCRYPT_DEFAULT_R,
    p: int = _SCRYPT_DEFAULT_P,
) -> str:
    if not password or len(password.encode("utf-8")) > 1024:
        raise ValueError("password length is outside the supported range")
    _validate_scrypt_parameters(n, r, p)
    salt = os.urandom(_SCRYPT_SALT_BYTES)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=n,
        r=r,
        p=p,
        dklen=_SCRYPT_HASH_BYTES,
        maxmem=_SCRYPT_MAX_MEMORY,
    )
    return f"scrypt${n}${r}${p}${_b64encode(salt)}${_b64encode(digest)}"


def _parse_password_hash(encoded: str) -> _PasswordHash:
    parts = encoded.split("$")
    if len(parts) != 6 or parts[0] != "scrypt":
        raise ValueError("invalid scrypt password hash")
    try:
        n, r, p = (int(value) for value in parts[1:4])
        _validate_scrypt_parameters(n, r, p)
        salt = _b64decode(parts[4])
        digest = _b64decode(parts[5])
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid scrypt password hash") from exc
    if len(salt) < 16 or len(digest) != _SCRYPT_HASH_BYTES:
        raise ValueError("invalid scrypt password hash")
    return _PasswordHash(n=n, r=r, p=p, salt=salt, digest=digest)


def _verify_scrypt(password: str, password_hash: _PasswordHash) -> bool:
    if not password or len(password.encode("utf-8")) > 1024:
        return False
    try:
        candidate = hashlib.scrypt(
            password.encode("utf-8"),
            salt=password_hash.salt,
            n=password_hash.n,
            r=password_hash.r,
            p=password_hash.p,
            dklen=len(password_hash.digest),
            maxmem=_SCRYPT_MAX_MEMORY,
        )
    except (ValueError, MemoryError, OSError):
        return False
    return hmac.compare_digest(candidate, password_hash.digest)


def _credential_verifier() -> CredentialVerifier:
    issuer = os.getenv("OIDC_ISSUER", "").strip()
    audience = os.getenv("OIDC_AUDIENCE", "").strip()
    configured_jwks_url = os.getenv("OIDC_JWKS_URL", "").strip()
    if issuer or audience or configured_jwks_url:
        if not issuer or not audience:
            raise AuthenticationConfigurationError(
                "OIDC_ISSUER and OIDC_AUDIENCE must be configured together."
            )
        _validate_oidc_endpoint(issuer, "OIDC_ISSUER")
        person_number_claim = os.getenv(
            "OIDC_PERSON_NUMBER_CLAIM", "person_number"
        ).strip()
        username_claim = os.getenv("OIDC_USERNAME_CLAIM", "preferred_username").strip()
        if not person_number_claim or not username_claim:
            raise AuthenticationConfigurationError(
                "OIDC claim names must not be empty."
            )
        return OidcTokenVerifier(
            issuer=issuer,
            audience=audience,
            algorithms=_oidc_algorithms(),
            person_number_claim=person_number_claim,
            username_claim=username_claim,
        )
    raw_users = os.getenv("AUTH_USERS", "").strip()
    if raw_users:
        try:
            return LocalCredentialVerifier.from_mapping(raw_users)
        except (AuthenticationConfigurationError, ValueError) as exc:
            raise AuthenticationConfigurationError(
                "AUTH_USERS contains an invalid scrypt credential configuration."
            ) from exc
    legacy_password = os.getenv("AUTH_PASSWORD", "")
    if (
        is_development_or_test()
        and legacy_password
        and not _is_insecure_placeholder(legacy_password)
    ):
        return LegacyDevelopmentVerifier(legacy_password)
    raise AuthenticationConfigurationError(
        "Authentication is not configured. Configure OIDC or AUTH_USERS."
    )


def get_credential_verifier() -> CredentialVerifier:
    return _credential_verifier()


def _is_insecure_placeholder(value: str | None) -> bool:
    if not value:
        return True
    normalized = value.strip().lower()
    return any(
        marker in normalized
        for marker in (
            "replace-with",
            "generate_a_secure",
            "your_secure",
            "your-",
            "change-me",
            "changeme",
        )
    )


_fallback_jwt_secret: str | None = None
_jwt_secret_lock = Lock()


def _jwt_secret() -> str:
    global _fallback_jwt_secret
    secret = os.getenv("SESSION_SECRET_KEY")
    if _is_insecure_placeholder(secret):
        secret = None
    if not secret:
        if is_dev_mode() or is_test_mode():
            if _fallback_jwt_secret is None:
                with _jwt_secret_lock:
                    if _fallback_jwt_secret is None:
                        logger.warning(
                            "SESSION_SECRET_KEY is not set; using an ephemeral test/development secret."
                        )
                        _fallback_jwt_secret = secrets.token_urlsafe(32)
            return _fallback_jwt_secret
        raise RuntimeError(
            "SESSION_SECRET_KEY is required outside development and test."
        )
    if not is_development_or_test() and len(secret.encode("utf-8")) < 32:
        raise RuntimeError(
            "SESSION_SECRET_KEY must contain at least 32 bytes in production."
        )
    return secret


def _ttl_seconds() -> int:
    try:
        return int(os.getenv("SESSION_TTL_SECONDS", str(8 * 60 * 60)))
    except ValueError:
        raise RuntimeError("SESSION_TTL_SECONDS must be an integer.") from None


def cookie_secure() -> bool:
    value = os.getenv("SESSION_COOKIE_SECURE")
    if value is None:
        return True
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _session_cookie_name() -> str:
    return f"__Host-{SESSION_COOKIE_NAME}" if cookie_secure() else SESSION_COOKIE_NAME


def _session_samesite() -> Literal["lax", "strict", "none"]:
    raw = os.getenv("SESSION_COOKIE_SAMESITE", "strict").strip().lower()
    value = raw if raw in {"lax", "strict", "none"} else "strict"
    if value == "none" and not cookie_secure():
        raise RuntimeError(
            "SESSION_COOKIE_SAMESITE=none requires SESSION_COOKIE_SECURE=true."
        )
    return cast(Literal["lax", "strict", "none"], value)


def set_csrf_cookie(
    response: Response, csrf_token: str, csrf_cookie_name: str = "csrf_token"
) -> None:
    response.set_cookie(
        key=csrf_cookie_name,
        value=csrf_token,
        httponly=False,
        secure=cookie_secure(),
        samesite=_session_samesite(),
        max_age=_ttl_seconds(),
        path="/",
    )
    response.headers["X-CSRF-Token"] = csrf_token


def set_auth_cookies(
    response: Response,
    session_token: str,
    csrf_token: str,
    csrf_cookie_name: str = "csrf_token",
) -> None:
    max_age = _ttl_seconds()
    response.set_cookie(
        key=_session_cookie_name(),
        value=session_token,
        httponly=True,
        secure=cookie_secure(),
        samesite=_session_samesite(),
        max_age=max_age,
        path="/",
    )
    set_csrf_cookie(response, csrf_token, csrf_cookie_name)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


def clear_auth_cookies(
    response: Response, csrf_cookie_name: str = "csrf_token"
) -> None:
    is_secure = cookie_secure()
    samesite = _session_samesite()
    cookie_names = {_session_cookie_name(), SESSION_COOKIE_NAME}
    cookie_names.add(f"__Host-{SESSION_COOKIE_NAME}")
    for cookie_name in cookie_names:
        response.delete_cookie(
            cookie_name,
            path="/",
            secure=is_secure,
            httponly=True,
            samesite=samesite,
        )
    response.delete_cookie(
        csrf_cookie_name,
        path="/",
        secure=is_secure,
        httponly=False,
        samesite=samesite,
    )
    response.headers["Cache-Control"] = "no-store"


def session_cookie_token(request: Request) -> str | None:
    return (
        request.cookies.get(_session_cookie_name())
        or request.cookies.get(SESSION_COOKIE_NAME)
        or request.cookies.get(f"__Host-{SESSION_COOKIE_NAME}")
    )


@dataclass(frozen=True)
class SessionContext:
    employee_id: str
    username: str
    full_name: str
    session_id: str = ""


def create_session(employee: Employee) -> str:
    issued_at = int(time.time())
    payload = {
        "sub": employee.employee_id,
        "username": employee.username,
        "iss": SESSION_TOKEN_ISSUER,
        "aud": SESSION_TOKEN_AUDIENCE,
        "iat": issued_at,
        "exp": issued_at + _ttl_seconds(),
        "jti": secrets.token_urlsafe(18),
    }
    return jwt.encode(payload, _jwt_secret(), algorithm=JWT_ALGORITHM)


def _decode_session_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token,
            _jwt_secret(),
            algorithms=[JWT_ALGORITHM],
            issuer=SESSION_TOKEN_ISSUER,
            audience=SESSION_TOKEN_AUDIENCE,
            options={
                "require": ["sub", "username", "iss", "aud", "iat", "exp", "jti"],
                "verify_signature": True,
                "verify_exp": True,
                "verify_iat": True,
                "verify_iss": True,
                "verify_aud": True,
            },
        )
    except jwt.PyJWTError:
        raise AuthenticationError("Invalid session token.") from None
    if (
        not isinstance(payload.get("sub"), str)
        or not payload["sub"]
        or not isinstance(payload.get("username"), str)
        or not payload["username"]
        or not isinstance(payload.get("jti"), str)
        or not payload["jti"]
        or isinstance(payload.get("exp"), bool)
        or not isinstance(payload.get("exp"), (int, float))
    ):
        raise AuthenticationError("Invalid session token.")
    return payload


async def activate_session(token: str, employee: Employee) -> None:
    try:
        payload = _decode_session_token(token)
    except AuthenticationError:
        raise RuntimeError("Refusing to activate an invalid session token.") from None
    if (
        payload["sub"] != employee.employee_id
        or payload["username"] != employee.username
    ):
        raise RuntimeError("Session identity does not match employee identity.")
    expires_at = float(payload["exp"])
    ttl_seconds = max(1, int(expires_at - time.time()))
    await _blocklist().store_session(
        str(payload["jti"]),
        StoredSession(
            employee_id=employee.employee_id,
            username=employee.username,
            full_name=employee.full_name,
            expires_at=expires_at,
        ),
        ttl_seconds,
    )


async def issue_session(employee: Employee) -> str:
    token = create_session(employee)
    await activate_session(token, employee)
    return token


async def resolve(token: str | None) -> SessionContext | None:
    if not token or len(token) > 32768:
        return None
    try:
        payload = _decode_session_token(token)
    except AuthenticationError:
        return None
    session_id = str(payload["jti"])
    stored_session = await _blocklist().get_session(session_id)
    if stored_session is None:
        return None
    if (
        stored_session.employee_id != payload["sub"]
        or stored_session.username != payload["username"]
        or stored_session.expires_at <= time.time()
    ):
        return None
    context = SessionContext(
        employee_id=stored_session.employee_id,
        username=stored_session.username,
        full_name=stored_session.full_name,
        session_id=session_id,
    )
    set_authenticated_ws_identity(context.employee_id)
    return context


async def destroy(sid: str | None) -> None:
    if not sid:
        return
    try:
        payload = _decode_session_token(sid)
    except AuthenticationError:
        return
    ttl_seconds = max(1, int(float(payload["exp"]) - time.time()))
    await _blocklist().revoke_session(str(payload["jti"]), ttl_seconds)


async def current_session(
    otl_session: str | None = Cookie(default=None, alias=_session_cookie_name()),
) -> SessionContext:
    try:
        context = await resolve(otl_session)
    except SessionStoreUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Session validation is temporarily unavailable.",
            headers={"Retry-After": "1"},
        ) from exc
    if not context:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or invalid. Please sign in again.",
        )
    return context


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        raise AuthenticationConfigurationError(f"{name} must be numeric.") from None


def _oidjwks_cache_seconds() -> float:
    return max(30.0, min(3600.0, _float_env("OIDC_JWKS_CACHE_SECONDS", 300.0)))


def _oidc_discovery_cache_seconds() -> float:
    return max(30.0, min(3600.0, _float_env("OIDC_DISCOVERY_CACHE_SECONDS", 300.0)))


def _oidc_refresh_minimum_seconds() -> float:
    return max(1.0, min(300.0, _float_env("OIDC_JWKS_REFRESH_MIN_SECONDS", 30.0)))


def _clear_oidc_caches() -> None:
    _JWKS_CACHE.clear()
    _DISCOVERY_CACHE.clear()
