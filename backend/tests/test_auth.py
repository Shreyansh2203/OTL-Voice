import time
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from backend.core.auth import (
    _STORE,
    _prune,
    create_session,
    current_session,
    destroy,
    resolve,
)
from backend.models import Employee


@pytest.fixture(autouse=True)
def clear_store():
    _STORE.clear()
    import backend.core.auth
    backend.core.auth._LAST_PRUNE = 0.0
    yield
    _STORE.clear()

def test_create_session():
    employee = Employee(employee_id="123", username="testuser", full_name="Test User")
    sid = create_session(employee)
    assert sid in _STORE
    assert _STORE[sid].employee_id == "123"

def test_create_session_max_sessions():
    employee = Employee(employee_id="123", username="testuser", full_name="Test User")
    
    with patch("backend.core.auth.MAX_SESSIONS", 0):
        with pytest.raises(HTTPException) as exc:
            create_session(employee)
        assert exc.value.status_code == 503

def test_resolve():
    employee = Employee(employee_id="123", username="testuser", full_name="Test User")
    sid = create_session(employee)
    
    ctx = resolve(sid)
    assert ctx is not None
    assert ctx.employee_id == "123"
    
    # Missing sid
    assert resolve(None) is None
    
    # Invalid sid
    assert resolve("invalid") is None

def test_resolve_expired():
    employee = Employee(employee_id="123", username="testuser", full_name="Test User")
    sid = create_session(employee)
    
    with patch("time.time", return_value=time.time() + 999999):
        assert resolve(sid) is None
        assert sid not in _STORE

def test_destroy():
    employee = Employee(employee_id="123", username="testuser", full_name="Test User")
    sid = create_session(employee)
    
    destroy(sid)
    assert sid not in _STORE
    
    # None sid
    destroy(None)

def test_prune():
    employee = Employee(employee_id="123", username="testuser", full_name="Test User")
    
    # Create an expired session
    with patch("backend.core.auth._ttl_seconds", return_value=-10):
        sid1 = create_session(employee)
    
    # Prune should be called inside create_session and last prune is updated.
    # We will reset _LAST_PRUNE to trigger again
    import backend.core.auth
    backend.core.auth._LAST_PRUNE = 0.0
    
    _prune()
    assert sid1 not in _STORE
    
    # Test skipping prune
    backend.core.auth._LAST_PRUNE = time.time()
    sid2 = create_session(employee) # ttl is positive now since patch is gone
    _STORE[sid2].expires_at = time.time() - 10
    
    _prune() # Should not prune because < 60s
    assert sid2 in _STORE
    

def test_current_session():
    employee = Employee(employee_id="123", username="testuser", full_name="Test User")
    sid = create_session(employee)
    
    ctx = current_session(otl_session=sid)
    assert ctx.employee_id == "123"
    
    with pytest.raises(HTTPException) as exc:
        current_session(otl_session=None)
    assert exc.value.status_code == 401

def test_cookie_secure():
    import os

    from backend.core.auth import cookie_secure
    with patch.dict(os.environ, {"SESSION_COOKIE_SECURE": "false"}):
        assert cookie_secure() is False
    with patch.dict(os.environ, {"SESSION_COOKIE_SECURE": "true"}):
        assert cookie_secure() is True
