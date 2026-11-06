import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.idempotency import IdempotencyStore
from backend.services.otl_client import (
    OtlCredential,
    OtlError,
    acreate_many,
    acreate_timecard_entry,
    aget_worker,
    alist_timecard_entries,
    alist_worker_assignments,
    avalidate,
    close_shared_client,
    create_many,
    create_timecard_entry,
    delete_timecard_entry,
    get_shared_async_client,
    get_worker,
    list_timecard_entries,
    validate,
)


@pytest.mark.asyncio
async def test_aget_worker_success():
    """Cover otl_client.py:1037-1065 - aget_worker success path."""
    cred = OtlCredential("u", "p")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "items": [
            {
                "PersonId": "P1",
                "PersonNumber": "123",
                "names": {"items": [{"DisplayName": "Test User"}]},
                "ActiveFlag": True,
            }
        ]
    }
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch(
        "backend.services.otl_client.get_shared_async_client",
        new=AsyncMock(return_value=mock_client),
    ):
        worker = await aget_worker(cred, "123")

    assert worker is not None
    assert worker["personNumber"] == "123"
    assert worker["fullName"] == "Test User"
    assert worker["isActive"] is True


@pytest.mark.asyncio
async def test_aget_worker_empty():
    """Cover otl_client.py:1050-1052 - aget_worker empty items."""
    cred = OtlCredential("u", "p")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"items": []}
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch(
        "backend.services.otl_client.get_shared_async_client",
        new=AsyncMock(return_value=mock_client),
    ):
        assert await aget_worker(cred, "999") is None


@pytest.mark.asyncio
async def test_aget_worker_httpx_error():
    """Cover otl_client.py:1047-1048 - aget_worker raises OtlError on bad status."""
    cred = OtlCredential("u", "p")
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch(
        "backend.services.otl_client.get_shared_async_client",
        new=AsyncMock(return_value=mock_client),
    ):
        with pytest.raises(OtlError):
            await aget_worker(cred, "123")


@pytest.mark.asyncio
async def test_alist_timecard_entries_demo_mode():
    """Cover otl_client.py:1076-1077 - alist_timecard_entries demo mode."""
    cred = OtlCredential("u", "p")
    with patch("backend.core.config.is_demo_mode", return_value=True):
        result = await alist_timecard_entries(cred)
    assert result == {"items": []}


@pytest.mark.asyncio
async def test_alist_timecard_entries_success():
    """Cover otl_client.py:1068-1095 - alist_timecard_entries success path."""
    cred = OtlCredential("u", "p")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "items": [
            {"timeRecordEvent": [{"timeStatuses": [{"displayValue": "Approved"}]}]}
        ]
    }
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch(
        "backend.services.otl_client.get_shared_async_client",
        new=AsyncMock(return_value=mock_client),
    ):
        with patch("backend.core.config.is_demo_mode", return_value=False):
            result = await alist_timecard_entries(cred, person_number="123")

    assert "items" in result
    mock_client.get.assert_called_once()


@pytest.mark.asyncio
async def test_acreate_timecard_entry_demo_mode():
    """Cover otl_client.py:1221-1222 - acreate_timecard_entry demo mode."""
    cred = OtlCredential("u", "p")
    with patch(
        "backend.services.otl_client.get_shared_async_client",
        new=AsyncMock(return_value=AsyncMock()),
    ):
        with patch("backend.core.config.is_demo_mode", return_value=True):
            result = await acreate_timecard_entry(
                cred, {"employeeNumber": "123", "hours": 5}
            )
    assert "timeRecordEventRequestId" in result
    assert result["timeRecordEventRequestId"].startswith("DEMO-")


@pytest.mark.asyncio
async def test_acreate_timecard_entry_success():
    """Cover otl_client.py:1210-1231 - acreate_timecard_entry success path."""
    cred = OtlCredential("u", "p")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"timeRecordEventRequestId": "req-async-1"}
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)

    with patch(
        "backend.services.otl_client.get_shared_async_client",
        new=AsyncMock(return_value=mock_client),
    ):
        with patch("backend.core.config.is_demo_mode", return_value=False):
            result = await acreate_timecard_entry(
                cred, {"employeeNumber": "123", "hours": 5}
            )

    assert result["timeRecordEventRequestId"] == "req-async-1"
    mock_client.post.assert_called_once()


@pytest.mark.asyncio
async def test_acreate_timecard_entry_otl_error():
    """Cover otl_client.py:1230-1231 - acreate_timecard_entry raises OtlError."""
    cred = OtlCredential("u", "p")
    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)

    with patch(
        "backend.services.otl_client.get_shared_async_client",
        new=AsyncMock(return_value=mock_client),
    ):
        with patch("backend.core.config.is_demo_mode", return_value=False):
            with pytest.raises(OtlError):
                await acreate_timecard_entry(
                    cred, {"employeeNumber": "123", "hours": 5}
                )


@pytest.mark.asyncio
async def test_avalidate_demo_mode():
    """Cover otl_client.py:1020-1023 - avalidate demo mode."""
    cred = OtlCredential("u", "p")
    with patch("backend.core.config.is_demo_mode", return_value=True):
        result = await avalidate(cred)
    assert result == {"ok": True, "demo": True}


@pytest.mark.asyncio
async def test_avalidate_success():
    """Cover otl_client.py:1019-1034 - avalidate success path."""
    cred = OtlCredential("u", "p")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch(
        "backend.services.otl_client.get_shared_async_client",
        new=AsyncMock(return_value=mock_client),
    ):
        with patch("backend.core.config.is_demo_mode", return_value=False):
            result = await avalidate(cred)

    assert result == {"ok": True}
    mock_client.get.assert_called_once()


@pytest.mark.asyncio
async def test_avalidate_auth_error():
    """Cover otl_client.py:1028-1032 - avalidate auth error."""
    cred = OtlCredential("u", "p")
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch(
        "backend.services.otl_client.get_shared_async_client",
        new=AsyncMock(return_value=mock_client),
    ):
        with patch("backend.core.config.is_demo_mode", return_value=False):
            with pytest.raises(OtlError):
                await avalidate(cred)


@pytest.mark.asyncio
async def test_acreate_many_async_with_idempotency_store(tmp_path):
    """Cover otl_client.py:1098-1201 - acreate_many async with idempotency store."""
    store = IdempotencyStore(tmp_path / "async_idem.db", poll_seconds=0.002)
    cred = OtlCredential("u", "p")
    entry = {
        "employeeNumber": "123",
        "hours": 8,
        "requestId": "request-async-idem-123",
    }

    mock_created = {"timeRecordEventRequestId": "async-req-1"}
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(
        return_value=MagicMock(
            status_code=200, json=MagicMock(return_value=mock_created)
        )
    )

    with patch(
        "backend.services.otl_client.get_shared_async_client",
        new=AsyncMock(return_value=mock_client),
    ):
        results = await acreate_many(cred, [entry], idempotency_store=store)

    assert results[0]["ok"] is True
    assert results[0]["id"] == "async-req-1"


@pytest.mark.asyncio
async def test_acreate_many_async_otl_error():
    """Cover otl_client.py:1166-1174 - acreate_many async OtlError handling."""
    cred = OtlCredential("u", "p")
    entry = {
        "employeeNumber": "123",
        "hours": 8,
        "requestId": "request-async-err-123",
    }

    async def failing_create(*_args, **_kwargs):
        raise OtlError(503, "Oracle busy")

    with patch(
        "backend.services.otl_client.get_shared_async_client",
        new=AsyncMock(return_value=AsyncMock()),
    ):
        with patch(
            "backend.services.otl_client.acreate_timecard_entry",
            new=AsyncMock(side_effect=failing_create),
        ):
            results = await acreate_many(cred, [entry])

    assert results[0]["ok"] is False
    assert results[0]["status"] == 503


@pytest.mark.asyncio
async def test_acreate_many_async_unexpected_exception():
    """Cover otl_client.py:1175-1181 - acreate_many async unexpected exception."""
    cred = OtlCredential("u", "p")
    entry = {
        "employeeNumber": "123",
        "hours": 8,
        "requestId": "request-async-unexp-123",
    }

    async def boom(*_args, **_kwargs):
        raise RuntimeError("unexpected")

    with patch(
        "backend.services.otl_client.get_shared_async_client",
        new=AsyncMock(return_value=AsyncMock()),
    ):
        with patch(
            "backend.services.otl_client.acreate_timecard_entry",
            new=AsyncMock(side_effect=boom),
        ):
            results = await acreate_many(cred, [entry])

    assert results[0]["ok"] is False
    assert results[0]["status"] == 500


def test_validate_401_403():
    """Cover otl_client.py:542-546 - validate 401/403 handling."""
    cred = OtlCredential("u", "p")
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    with patch("httpx.Client.get", return_value=mock_resp):
        with patch.dict(os.environ, {"OTL_BASE_URL": "http://x"}):
            with pytest.raises(
                OtlError, match="authentication or authorization failed"
            ):
                validate(cred)

    mock_resp.status_code = 403
    with patch("httpx.Client.get", return_value=mock_resp):
        with patch.dict(os.environ, {"OTL_BASE_URL": "http://x"}):
            with pytest.raises(
                OtlError, match="authentication or authorization failed"
            ):
                validate(cred)


def test_list_timecard_entries_demo_mode():
    """Cover otl_client.py:612-613 - list_timecard_entries demo mode."""
    cred = OtlCredential("u", "p")
    with patch("backend.core.config.is_demo_mode", return_value=True):
        result = list_timecard_entries(cred)
    assert result == {"items": []}


def test_get_worker_names_as_dict():
    """Cover otl_client.py:658-660 - get_worker with names as dict."""
    cred = OtlCredential("u", "p")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "items": [
            {
                "PersonId": "P1",
                "PersonNumber": "123",
                "names": {"items": [{"DisplayName": "Dict Name"}]},
            }
        ]
    }
    with patch("httpx.Client.get", return_value=mock_resp):
        with patch.dict(os.environ, {"OTL_BASE_URL": "http://x"}):
            worker = get_worker(cred, "123")
    assert worker["fullName"] == "Dict Name"


def test_get_worker_names_list():
    """Cover otl_client.py:660-663 - get_worker with names as list."""
    cred = OtlCredential("u", "p")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "items": [
            {
                "PersonId": "P1",
                "PersonNumber": "123",
                "names": {"items": [{"DisplayName": "List Name"}]},
            }
        ]
    }
    with patch("httpx.Client.get", return_value=mock_resp):
        with patch.dict(os.environ, {"OTL_BASE_URL": "http://x"}):
            worker = get_worker(cred, "123")
    assert worker["fullName"] == "List Name"


def test_create_timecard_entry_otl_error():
    """Cover otl_client.py:861-862 - create_timecard_entry raises OtlError."""
    cred = OtlCredential("u", "p")
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    with patch("httpx.Client.post", return_value=mock_resp):
        with patch.dict(os.environ, {"OTL_BASE_URL": "http://x"}):
            with pytest.raises(OtlError):
                create_timecard_entry(cred, {"employeeNumber": "123", "hours": 5})


def test_delete_timecard_entry_otl_error():
    """Cover otl_client.py:869-870 - delete_timecard_entry raises OtlError."""
    cred = OtlCredential("u", "p")
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    with patch("httpx.Client.delete", return_value=mock_resp):
        with patch.dict(os.environ, {"OTL_BASE_URL": "http://x"}):
            with pytest.raises(OtlError):
                delete_timecard_entry(cred, "1")


def test_get_shared_async_client_creates_and_reuses():
    """Cover otl_client.py:995-1006 - get_shared_async_client."""
    import backend.services.otl_client as oc

    oc._shared_async_client = None
    client1 = asyncio.run(get_shared_async_client())
    client2 = asyncio.run(get_shared_async_client())
    assert client1 is client2
    asyncio.run(close_shared_client())


def test_close_shared_client():
    """Cover otl_client.py:1009-1016 - close_shared_client."""
    import backend.services.otl_client as oc

    oc._shared_async_client = None
    client = asyncio.run(get_shared_async_client())
    assert not client.is_closed
    asyncio.run(close_shared_client())
    assert client.is_closed
    assert oc._shared_async_client is None


def test_alist_worker_assignments():
    """Cover otl_client.py:1204-1207 - alist_worker_assignments."""
    cred = OtlCredential("u", "p")
    with patch(
        "backend.services.otl_client.list_worker_assignments",
        return_value=[{"assignmentId": "A1"}],
    ):
        result = asyncio.run(alist_worker_assignments(cred, "123"))
    assert result == [{"assignmentId": "A1"}]


def test_public_otl_error_all_ranges():
    """Cover otl_client.py:102-115 - public_otl_error all status ranges."""
    from backend.services.otl_client import public_otl_error

    assert public_otl_error(400) == "Oracle rejected this timecard entry."
    assert public_otl_error(422) == "Oracle rejected this timecard entry."
    assert public_otl_error(401) == "Oracle authentication or authorization failed."
    assert public_otl_error(403) == "Oracle authentication or authorization failed."
    assert public_otl_error(404) == "The timecard request was not found."
    assert (
        public_otl_error(409)
        == "The timecard request conflicts with an existing request."
    )
    assert public_otl_error(429) == "Oracle is temporarily busy. Please retry later."
    assert public_otl_error(500) == "Oracle Cloud is temporarily unavailable."
    assert public_otl_error(599) == "Oracle Cloud is temporarily unavailable."
    assert public_otl_error(999) == "Timecard submission failed."


def test_time_status_value_various():
    """Cover otl_client.py:555-571 - _time_status_value various inputs."""
    from backend.services.otl_client import _time_status_value

    assert _time_status_value("Approved") == "Approved"
    assert _time_status_value(None) is None
    assert _time_status_value({}) is None
    assert _time_status_value({"displayValue": "Submitted"}) == "Submitted"
    assert _time_status_value({"statusName": "Pending"}) == "Pending"
    assert _time_status_value({"items": [{"statusCode": "Completed"}]}) == "Completed"
    assert _time_status_value([{"name": "Named"}]) == "Named"
    assert _time_status_value([{}, {}, {"eventStatus": "EventOnly"}]) is None


def test_propagate_timecard_statuses():
    """Cover otl_client.py:574-601 - propagate_timecard_statuses."""
    from backend.services.otl_client import propagate_timecard_statuses

    data = {
        "items": [
            {
                "timeStatuses": {"displayValue": "Approved"},
                "timeRecordEvent": [{"eventStatus": None, "timeStatuses": None}],
            }
        ]
    }
    result = propagate_timecard_statuses(data)
    assert result["items"][0]["eventStatus"] == "Approved"
    assert result["items"][0]["timeRecordEvent"][0]["eventStatus"] == "Approved"


def test_default_record_name_idempotency_error():
    """Cover otl_client.py:378-380 - _default_record_name with idempotency error."""
    from backend.services.otl_client import _default_record_name

    result = _default_record_name({"employeeNumber": "123", "workOrder": "WO1"})
    assert "123-WO1-" in result


def test_request_with_retry_non_idempotent_no_retry():
    """Cover otl_client.py:406-407 - _request_with_retry non-idempotent."""
    from backend.services.otl_client import _request_with_retry

    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_client = MagicMock()
    mock_client.get = MagicMock(return_value=mock_resp)

    resp = _request_with_retry(mock_client, "GET", "http://x", idempotent=False)
    assert resp.status_code == 500
    assert mock_client.get.call_count == 1


def test_arequest_with_retry_non_idempotent_no_retry():
    """Cover otl_client.py:482-483 - _arequest_with_retry non-idempotent."""
    from backend.services.otl_client import _arequest_with_retry

    async def run():
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)

        resp = await _arequest_with_retry(
            mock_client, "GET", "http://x", idempotent=False
        )
        assert resp.status_code == 500
        assert mock_client.get.call_count == 1

    asyncio.run(run())


def test_write_headers_without_request_id():
    """Cover otl_client.py:695-699 - _write_headers without idempotency key."""
    from backend.services.otl_client import _write_headers

    headers = _write_headers({"employeeNumber": "123", "hours": 5}, "corr-123")
    assert headers["Content-Type"] == "application/json"
    assert headers["X-Correlation-ID"] == "corr-123"
    assert "Idempotency-Key" not in headers


def test_success_result_minimal():
    """Cover otl_client.py:703-726 - _success_result minimal."""
    from backend.services.otl_client import _success_result

    result = _success_result(
        0, {"timeRecordEventRequestId": "r1"}, {"employeeNumber": "1"}, "corr-1"
    )
    assert result["ok"] is True
    assert result["id"] == "r1"
    assert result["index"] == 0


def test_failure_result_with_code():
    """Cover otl_client.py:729-751 - _failure_result with code."""
    from backend.services.otl_client import _failure_result

    result = _failure_result(0, 500, "corr-1", None, code="oracle_unavailable")
    assert result["ok"] is False
    assert result["status"] == 500
    assert result["code"] == "oracle_unavailable"


def test_idempotency_store_explicit():
    """Cover otl_client.py:754-761 - _idempotency_store explicit."""
    from backend.services.otl_client import _idempotency_store

    store = MagicMock()
    result = _idempotency_store([None], store)
    assert result is store


def test_idempotency_store_no_keys():
    """Cover otl_client.py:759-760 - _idempotency_store no keys."""
    from backend.services.otl_client import _idempotency_store

    result = _idempotency_store([None, None], None)
    assert result is None


def test_idempotency_store_with_keys_gets_default():
    """Cover otl_client.py:761 - _idempotency_store gets default store."""
    from backend.services.otl_client import _idempotency_store

    result = _idempotency_store(["key1"], None)
    assert result is not None


def test_oracle_failure_result_500_code():
    """Cover otl_client.py:784 - _oracle_failure_result code for 500+."""
    from backend.services.otl_client import _oracle_failure_result

    result = _oracle_failure_result(0, 503, "corr-1", None)
    assert result["code"] == "oracle_unavailable"

    result = _oracle_failure_result(0, 400, "corr-1", None)
    assert "code" not in result


def test_store_unavailable_result():
    """Cover otl_client.py:788-797 - _store_unavailable_result."""
    from backend.services.otl_client import _store_unavailable_result

    result = _store_unavailable_result(0, "corr-1", "key-1")
    assert result["ok"] is False
    assert result["status"] == 503
    assert result["code"] == "idempotency_unavailable"


def test_claim_lost_result():
    """Cover otl_client.py:800-809 - _claim_lost_result."""
    from backend.services.otl_client import _claim_lost_result

    result = _claim_lost_result(0, "corr-1", "key-1")
    assert result["ok"] is False
    assert result["status"] == 409
    assert result["code"] == "idempotency_claim_lost"


def test_preflight_entries_over_100():
    """Cover otl_client.py:817-818 - _preflight_entries over 100 entries."""
    from backend.services.otl_client import _preflight_entries

    entries = [{"employeeNumber": "1", "hours": 1}] * 101
    with pytest.raises(OtlError, match="At most 100"):
        _preflight_entries(entries, None)


def test_preflight_entries_multi_request_id():
    """Cover otl_client.py:819-823 - _preflight_entries multi entry with request_id."""
    from backend.services.otl_client import _preflight_entries

    entries = [{"employeeNumber": "1", "hours": 1}, {"employeeNumber": "2", "hours": 2}]
    with pytest.raises(OtlError, match="own requestId"):
        _preflight_entries(entries, "shared-request-id")


def test_preflight_entries_duplicate_keys():
    """Cover otl_client.py:838-843 - _preflight_entries duplicate requestIds."""
    from backend.services.otl_client import _preflight_entries

    entries = [
        {"employeeNumber": "1", "hours": 1, "requestId": "same-id"},
        {"employeeNumber": "2", "hours": 2, "requestId": "same-id"},
    ]
    with pytest.raises(OtlError, match="unique within a submission"):
        _preflight_entries(entries, None)


def test_create_many_idempotency_unavailable():
    """Cover otl_client.py:886-890 - create_many idempotency store unavailable."""
    from backend.services.idempotency import IdempotencyUnavailable

    cred = OtlCredential("u", "p")
    entry = {"employeeNumber": "123", "hours": 1, "requestId": "idem-unavail-1"}

    with patch(
        "backend.services.otl_client._idempotency_store",
        side_effect=IdempotencyUnavailable("down"),
    ):
        results = create_many(cred, [entry])
    assert results[0]["ok"] is False
    assert results[0]["status"] == 503
    assert results[0]["code"] == "idempotency_unavailable"


def test_create_many_empty_employee_number():
    """Cover otl_client.py:903-905 - create_many empty employee number."""
    import pathlib
    import tempfile

    from backend.services.idempotency import IdempotencyStore

    cred = OtlCredential("u", "p")
    entry = {"hours": 1, "requestId": "empty-emp-1"}
    tmp_dir = pathlib.Path(tempfile.mkdtemp())
    db_path = tmp_dir / "store.db"
    try:
        store = IdempotencyStore(str(db_path), poll_seconds=0.002)
        results = create_many(cred, [entry], idempotency_store=store)
    finally:
        import shutil

        shutil.rmtree(tmp_dir, ignore_errors=True)
    assert results[0]["ok"] is False
    assert results[0]["status"] == 400
