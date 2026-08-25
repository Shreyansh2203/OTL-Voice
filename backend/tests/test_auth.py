# Set required env var for tests
import os
from unittest.mock import patch

import jwt
import pytest
from fastapi import HTTPException

os.environ["SESSION_SECRET_KEY"] = "test-secret-key-for-testing-only"

from backend.core.auth import (
    JWT_ALGORITHM,
    _jwt_secret,
    create_session,
    current_session,
    destroy,
    resolve,
)
from backend.models import Employee


def test_create_session():
    employee = Employee(employee_id="123", username="testuser", full_name="Test User")
    token = create_session(employee)
    
    payload = jwt.decode(token, _jwt_secret(), algorithms=[JWT_ALGORITHM])
    assert payload["sub"] == "123"
    assert payload["username"] == "testuser"
    assert payload["full_name"] == "Test User"


@pytest.mark.asyncio
async def test_resolve():
    employee = Employee(employee_id="123", username="testuser", full_name="Test User")
    token = create_session(employee)
    
    ctx = await resolve(token)
    assert ctx is not None
    assert ctx.employee_id == "123"
    
    # Missing sid
    assert await resolve(None) is None
    
    # Invalid sid
    assert await resolve("invalid") is None


@pytest.mark.asyncio
async def test_resolve_expired():
    employee = Employee(employee_id="123", username="testuser", full_name="Test User")
    
    with patch("backend.core.auth._ttl_seconds", return_value=-10):
        token = create_session(employee)
    
    assert await resolve(token) is None


@pytest.mark.asyncio
async def test_destroy():
    employee = Employee(employee_id="123", username="testuser", full_name="Test User")
    token = create_session(employee)
    
    # JWT destroy is a no-op server side
    await destroy(token)
    
    # None sid
    await destroy(None)


@pytest.mark.asyncio
async def test_current_session():
    employee = Employee(employee_id="123", username="testuser", full_name="Test User")
    token = create_session(employee)
    
    ctx = await current_session(otl_session=token)
    assert ctx.employee_id == "123"
    
    with pytest.raises(HTTPException) as exc:
        await current_session(otl_session=None)
    assert exc.value.status_code == 401


def test_cookie_secure():
    import os
    
    from backend.core.auth import cookie_secure
    
    with patch.dict(os.environ, {"SESSION_COOKIE_SECURE": "false"}):
        assert cookie_secure() is False
    with patch.dict(os.environ, {"SESSION_COOKIE_SECURE": "true"}):
        assert cookie_secure() is True