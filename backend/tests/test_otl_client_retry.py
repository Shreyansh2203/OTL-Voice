from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backend.services.otl_client import (
    OtlCredential,
    _arequest_with_retry,
    _request_with_retry,
    create_many,
)


@pytest.mark.asyncio
async def test_arequest_with_retry_http_503_then_success():
    """Cover otl_client.py:494-512 - async retry on retryable HTTP status."""
    cred = OtlCredential("u", "p")
    mock_resp_503 = MagicMock()
    mock_resp_503.status_code = 503
    mock_resp_200 = MagicMock()
    mock_resp_200.status_code = 200

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=[mock_resp_503, mock_resp_200])

    with patch("asyncio.sleep", new=AsyncMock()):
        with patch("backend.services.otl_client.random.random", return_value=0.5):
            resp = await _arequest_with_retry(
                mock_client,
                "GET",
                "http://x",
                cred=cred,
                idempotent=True,
                max_retries=1,
            )

    assert resp.status_code == 200
    assert mock_client.get.call_count == 2


@pytest.mark.asyncio
async def test_arequest_with_retry_http_503_exhausts_retries():
    """Cover otl_client.py:494-512 - async retry exhausts retries on 503."""
    cred = OtlCredential("u", "p")
    mock_resp_503 = MagicMock()
    mock_resp_503.status_code = 503
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp_503)

    with patch("asyncio.sleep", new=AsyncMock()):
        with patch("backend.services.otl_client.random.random", return_value=0.5):
            resp = await _arequest_with_retry(
                mock_client,
                "GET",
                "http://x",
                cred=cred,
                idempotent=True,
                max_retries=1,
            )

    assert resp.status_code == 503
    assert mock_client.get.call_count == 2


@pytest.mark.asyncio
async def test_arequest_with_retry_network_error_then_success():
    """Cover otl_client.py:514-534 - async retry on network error then success."""
    cred = OtlCredential("u", "p")
    mock_resp_200 = MagicMock()
    mock_resp_200.status_code = 200
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=[httpx.ConnectError("boom"), mock_resp_200])

    with patch("asyncio.sleep", new=AsyncMock()):
        with patch("backend.services.otl_client.random.random", return_value=0.5):
            resp = await _arequest_with_retry(
                mock_client,
                "GET",
                "http://x",
                cred=cred,
                idempotent=True,
                max_retries=1,
            )

    assert resp.status_code == 200
    assert mock_client.get.call_count == 2


@pytest.mark.asyncio
async def test_arequest_with_retry_network_error_exhausts():
    """Cover otl_client.py:514-534 - async retry exhausts on network error."""
    cred = OtlCredential("u", "p")
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=httpx.ConnectError("boom"))

    with patch("asyncio.sleep", new=AsyncMock()):
        with patch("backend.services.otl_client.random.random", return_value=0.5):
            with pytest.raises(httpx.ConnectError):
                await _arequest_with_retry(
                    mock_client,
                    "GET",
                    "http://x",
                    cred=cred,
                    idempotent=True,
                    max_retries=1,
                )

    assert mock_client.get.call_count == 2


@pytest.mark.asyncio
async def test_arequest_with_retry_non_idempotent_no_retry_on_503():
    """Cover otl_client.py:494-498 - async non-idempotent does not retry on 503."""
    cred = OtlCredential("u", "p")
    mock_resp_503 = MagicMock()
    mock_resp_503.status_code = 503
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp_503)

    with patch("asyncio.sleep", new=AsyncMock()):
        resp = await _arequest_with_retry(
            mock_client, "GET", "http://x", cred=cred, idempotent=False
        )

    assert resp.status_code == 503
    assert mock_client.get.call_count == 1


def test_request_with_retry_http_503_then_success():
    """Cover otl_client.py:419-437 - sync retry on retryable HTTP status."""
    mock_resp_503 = MagicMock()
    mock_resp_503.status_code = 503
    mock_resp_200 = MagicMock()
    mock_resp_200.status_code = 200
    mock_client = MagicMock()
    mock_client.get = MagicMock(side_effect=[mock_resp_503, mock_resp_200])

    with patch("time.sleep", return_value=None):
        with patch("backend.services.otl_client.random.random", return_value=0.5):
            resp = _request_with_retry(
                mock_client, "GET", "http://x", idempotent=True, max_retries=1
            )

    assert resp.status_code == 200
    assert mock_client.get.call_count == 2


def test_request_with_retry_network_error_exhausts():
    """Cover otl_client.py:439-456 - sync retry exhausts on network error."""
    OtlCredential("u", "p")
    mock_client = MagicMock()
    mock_client.get = MagicMock(side_effect=httpx.ConnectError("boom"))

    with patch("time.sleep", return_value=None):
        with patch("backend.services.otl_client.random.random", return_value=0.5):
            with pytest.raises(httpx.ConnectError):
                _request_with_retry(
                    mock_client, "GET", "http://x", idempotent=True, max_retries=1
                )

    assert mock_client.get.call_count == 2


def test_create_many_sync_claim_replay_path():
    """Cover otl_client.py:917-918 - create_many sync claim replay."""
    import pathlib
    import shutil
    import tempfile

    from backend.services.idempotency import IdempotencyStore

    cred = OtlCredential("u", "p")
    entry = {
        "employeeNumber": "123",
        "hours": 8,
        "requestId": "sync-replay-123",
    }

    tmp_dir = pathlib.Path(tempfile.mkdtemp())
    db_path = tmp_dir / "store.db"
    try:
        store = IdempotencyStore(str(db_path), poll_seconds=0.002)

        # First submission
        mock_created = {"timeRecordEventRequestId": "sync-req-1"}
        with patch(
            "backend.services.otl_client.create_timecard_entry",
            return_value=mock_created,
        ):
            first = create_many(cred, [entry], idempotency_store=store)

        assert first[0]["ok"] is True
        assert first[0]["id"] == "sync-req-1"

        # Replay - should return cached result
        with patch(
            "backend.services.otl_client.create_timecard_entry",
            return_value=mock_created,
        ) as create_mock:
            replay = create_many(cred, [entry], idempotency_store=store)

        assert replay[0]["ok"] is True
        assert replay[0]["replayed"] is True
        assert create_mock.call_count == 0
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_create_many_sync_claim_pending_path():
    """Cover otl_client.py:930-946 - create_many sync claim pending path."""
    cred = OtlCredential("u", "p")
    entry = {"employeeNumber": "123", "hours": 8, "requestId": "sync-pending-456"}

    mock_store = MagicMock()
    mock_claim = MagicMock()
    mock_claim.state = "pending"
    mock_store.claim.return_value = mock_claim
    mock_store.wait_for_result.return_value = {
        "ok": True,
        "id": "pending-req",
        "replayed": True,
    }

    with patch(
        "backend.services.otl_client._idempotency_store", return_value=mock_store
    ):
        results = create_many(cred, [entry])

    assert results[0]["ok"] is True
    assert results[0]["id"] == "pending-req"
    assert results[0]["replayed"] is True


def test_create_many_sync_conflict_path():
    """Cover otl_client.py:920-928 - create_many sync conflict path."""
    cred = OtlCredential("u", "p")
    entry = {"employeeNumber": "123", "hours": 8, "requestId": "sync-conflict-123"}

    mock_store = MagicMock()
    mock_claim = MagicMock()
    mock_claim.state = "conflict"
    mock_claim.result = {"ok": False, "status": 409, "error": "conflict"}
    mock_claim.token = "token-123"
    mock_store.claim.return_value = mock_claim

    with patch(
        "backend.services.otl_client._idempotency_store", return_value=mock_store
    ):
        results = create_many(cred, [entry])

    assert results[0]["ok"] is False
    assert results[0]["status"] == 409


def test_create_many_sync_claim_unavailable():
    """Cover otl_client.py:909-915 - create_many sync claim IdempotencyUnavailable."""
    from backend.services.idempotency import IdempotencyUnavailable

    cred = OtlCredential("u", "p")
    entry = {"employeeNumber": "123", "hours": 8, "requestId": "sync-claim-unavail-123"}

    mock_store = MagicMock()
    mock_store.claim.side_effect = IdempotencyUnavailable("down")

    with patch(
        "backend.services.otl_client._idempotency_store", return_value=mock_store
    ):
        results = create_many(cred, [entry])

    assert results[0]["ok"] is False
    assert results[0]["status"] == 503
    assert results[0]["code"] == "idempotency_unavailable"


def test_create_many_sync_complete_failure():
    """Cover otl_client.py:973-978 - create_many sync complete IdempotencyUnavailable."""
    from backend.services.idempotency import IdempotencyUnavailable

    cred = OtlCredential("u", "p")
    entry = {"employeeNumber": "123", "hours": 8, "requestId": "sync-complete-fail-123"}

    mock_store = MagicMock()
    mock_claim = MagicMock()
    mock_claim.state = "new"
    mock_claim.token = "token-123"
    mock_store.claim.return_value = mock_claim
    mock_store.complete.side_effect = IdempotencyUnavailable("down")

    with patch(
        "backend.services.otl_client._idempotency_store", return_value=mock_store
    ):
        with patch(
            "backend.services.otl_client.create_timecard_entry",
            return_value={"timeRecordEventRequestId": "req-complete-fail"},
        ):
            results = create_many(cred, [entry])

    assert results[0]["ok"] is False
    assert results[0]["status"] == 503


def test_create_many_sync_complete_not_stored():
    """Cover otl_client.py:979-981 - create_many sync complete returns False."""
    cred = OtlCredential("u", "p")
    entry = {
        "employeeNumber": "123",
        "hours": 8,
        "requestId": "sync-complete-not-stored-123",
    }

    mock_store = MagicMock()
    mock_claim = MagicMock()
    mock_claim.state = "new"
    mock_claim.token = "token-123"
    mock_store.claim.return_value = mock_claim
    mock_store.complete.return_value = False

    with patch(
        "backend.services.otl_client._idempotency_store", return_value=mock_store
    ):
        with patch(
            "backend.services.otl_client.create_timecard_entry",
            return_value={"timeRecordEventRequestId": "req-not-stored"},
        ):
            results = create_many(cred, [entry])

    assert results[0]["ok"] is False
    assert results[0]["status"] == 409


def test_create_many_sync_unexpected_exception():
    """Cover otl_client.py:962-968 - create_many sync unexpected exception."""
    cred = OtlCredential("u", "p")
    entry = {"employeeNumber": "123", "hours": 8, "requestId": "sync-unexp-123"}

    mock_store = MagicMock()
    mock_claim = MagicMock()
    mock_claim.state = "new"
    mock_claim.token = "token-123"
    mock_store.claim.return_value = mock_claim

    with patch(
        "backend.services.otl_client._idempotency_store", return_value=mock_store
    ):
        with patch(
            "backend.services.otl_client.create_timecard_entry",
            side_effect=RuntimeError("unexpected"),
        ):
            results = create_many(cred, [entry])

    assert results[0]["ok"] is False
    assert results[0]["status"] == 500


def test_create_many_sync_claim_wait_for_result_unavailable():
    """Cover otl_client.py:933-937 - create_many sync wait_for_result IdempotencyUnavailable."""
    from backend.services.idempotency import IdempotencyUnavailable

    cred = OtlCredential("u", "p")
    entry = {"employeeNumber": "123", "hours": 8, "requestId": "sync-wait-unavail-123"}

    mock_store = MagicMock()
    mock_claim = MagicMock()
    mock_claim.state = "pending"
    mock_claim.token = "token-123"
    mock_store.claim.return_value = mock_claim
    mock_store.wait_for_result.side_effect = IdempotencyUnavailable("down")

    with patch(
        "backend.services.otl_client._idempotency_store", return_value=mock_store
    ):
        results = create_many(cred, [entry])

    assert results[0]["ok"] is False
    assert results[0]["status"] == 503
    assert results[0]["code"] == "idempotency_unavailable"


def test_request_with_retry_delete_method():
    """Cover otl_client.py:412-413 - sync retry DELETE method."""
    from backend.services.otl_client import _request_with_retry

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_client = MagicMock()
    mock_client.delete = MagicMock(return_value=mock_resp)

    resp = _request_with_retry(mock_client, "DELETE", "http://x", idempotent=True)
    assert resp.status_code == 200
    mock_client.delete.assert_called_once()


def test_request_with_retry_post_method():
    """Cover otl_client.py:414-415 - sync retry POST method."""
    from backend.services.otl_client import _request_with_retry

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_client = MagicMock()
    mock_client.post = MagicMock(return_value=mock_resp)

    resp = _request_with_retry(
        mock_client, "POST", "http://x", idempotent=True, json={"a": 1}
    )
    assert resp.status_code == 200
    mock_client.post.assert_called_once()
