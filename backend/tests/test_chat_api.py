

from __future__ import annotations

import asyncio
import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

# The credential verifier and the session store are chosen at request time from
# the environment, and neither is configured by default. The CI E2E job exports
# the same values; setting them here keeps this module runnable on its own.
os.environ.setdefault("AUTH_PASSWORD", "dummy-password")
os.environ.setdefault("ALLOW_IN_MEMORY_SESSIONS", "true")


@pytest.fixture
def auth_client(client: TestClient, mock_otl_client: MagicMock) -> TestClient:
    mock_otl_client.aget_worker.return_value = {
        "personNumber": "testuser",
        "fullName": "Pytest User",
    }
    mock_otl_client.aget_worker.side_effect = None
    response = client.post(
        "/api/auth/login", json={"username": "testuser", "password": "dummy-password"}
    )
    assert response.status_code == 200
    return client


def _messages(*contents: str) -> dict[str, Any]:
    return {
        "messages": [
            {"role": "user" if index % 2 == 0 else "assistant", "content": content}
            for index, content in enumerate(contents)
        ]
    }


def test_chat_ignores_blank_messages(
    auth_client: TestClient, mock_otl_client: MagicMock
) -> None:
    captured: dict[str, Any] = {}

    def _build(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "system prompt"

    with (
        patch("backend.api.v1.chat.chat.build_system_prompt", side_effect=_build),
        patch("backend.services.chat.stream_sse") as stream,
    ):
        stream.return_value = iter(["data: ok\n\n"])
        response = auth_client.post("/api/chat", json=_messages("hello", "   "))
    assert response.status_code == 200
    assert captured["username"] == "testuser"
    assert captured["recent_history"] == ""


def _catalogue_mock(**attributes: Any) -> MagicMock:
    catalogue = MagicMock()
    catalogue.alist_assignments_for_worker = AsyncMock(return_value=[])
    for name, value in attributes.items():
        setattr(catalogue, name, value)
    return catalogue


def test_chat_refuses_while_the_assignment_catalogue_is_unavailable(
    auth_client: TestClient, mock_otl_client: MagicMock
) -> None:
    """None means "catalogue not loaded", which is not "no assignments".

    build_system_prompt renders None as "this employee has no project assignments on
    record, tell them to contact their manager", so any failed catalogue refresh made
    the model confidently misinform the user. The write path already 503s on None.
    return MagicMock(side_effect=lambda: fake)


def test_stt_rejects_a_foreign_origin(auth_client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect) as raised:
        with auth_client.websocket_connect(
            "/api/stt/stream", headers={"origin": "https://attacker.example"}
        ) as websocket:
            websocket.receive_json()
    assert raised.value.code == 1008
    assert raised.value.reason == "Origin not allowed"


def test_stt_rejects_an_unauthenticated_client(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect) as raised:
        with client.websocket_connect("/api/stt/stream") as websocket:
            websocket.receive_json()
    assert raised.value.code == 1008
    assert raised.value.reason == "Unauthorized"


def test_stt_rejects_when_the_connection_budget_is_spent(
    auth_client: TestClient,
) -> None:
    with (
        patch("backend.api.v1.chat.ws_tracker") as tracker,
        patch("backend.services.oci_speech.STTClient") as factory,
    ):
        tracker.acquire = AsyncMock(return_value=False)
        fake = _FakeOciSttClient([])
        factory.side_effect = _stt_factory(fake)
        with pytest.raises(WebSocketDisconnect) as raised:
            with auth_client.websocket_connect("/api/stt/stream") as websocket:
                websocket.receive_json()
    assert raised.value.code == 1008
    assert raised.value.reason == "Too many connections"
    assert factory.call_count == 0


def test_stt_relays_transcripts_and_closes_the_oci_session(
    auth_client: TestClient,
) -> None:
    fake = _FakeOciSttClient([{"text": "logged four hours", "isFinal": True}])
    with patch("backend.services.oci_speech.STTClient", _stt_factory(fake)):
        with auth_client.websocket_connect("/api/stt/stream") as websocket:
            websocket.send_bytes(b"\x01\x02")
            assert websocket.receive_json() == {
                "text": "logged four hours",
                "isFinal": True,
            }
            websocket.send_bytes(b"")
    assert fake.sent == [b"\x01\x02"]
    assert fake.final_requested is True
    assert fake.closed is True


def test_stt_drops_frames_larger_than_the_chunk_limit(auth_client: TestClient) -> None:
    fake = _FakeOciSttClient([{"text": "ok", "isFinal": True}])
    with patch("backend.services.oci_speech.STTClient", _stt_factory(fake)):
        with auth_client.websocket_connect("/api/stt/stream") as websocket:
            websocket.send_bytes(b"x" * (64 * 1024 + 1))
            websocket.send_bytes(b"small")
            assert websocket.receive_json() == {"text": "ok", "isFinal": True}
            websocket.send_bytes(b"")
    assert fake.sent == [b"small"]


def test_stt_applies_backpressure_when_transcripts_back_up(
    auth_client: TestClient,
) -> None:
    fake = _FakeOciSttClient([{"text": "tail", "isFinal": True}], prefill=55)
    received: list[dict[str, Any]] = []
    with patch("backend.services.oci_speech.STTClient", _stt_factory(fake)):
        with auth_client.websocket_connect("/api/stt/stream") as websocket:
            websocket.send_bytes(b"chunk")
            for _ in range(56):
                received.append(websocket.receive_json())
            websocket.send_bytes(b"")
    assert received[0] == {"text": "prefill-0", "isFinal": False}
    assert received[-1] == {"text": "tail", "isFinal": True}
    assert fake.sent == [b"chunk"]


def test_stt_closes_the_socket_when_the_provider_is_unavailable(
    auth_client: TestClient,
) -> None:
    with patch("backend.services.oci_speech.STTClient") as factory:
        factory.side_effect = RuntimeError("no OCI quota")
        with pytest.raises(WebSocketDisconnect):
            with auth_client.websocket_connect("/api/stt/stream") as websocket:
                websocket.receive_json()


def test_stt_closes_the_socket_when_a_receive_frame_is_corrupt(
    auth_client: TestClient,
) -> None:
    class _Corrupt(_FakeOciSttClient):
        async def send_data(self, data: bytes) -> None:
            raise RuntimeError("codec failure")

    fake = _Corrupt([])
    with patch("backend.services.oci_speech.STTClient", _stt_factory(fake)):
        with pytest.raises(WebSocketDisconnect):
            with auth_client.websocket_connect("/api/stt/stream") as websocket:
                websocket.send_bytes(b"chunk")
                websocket.receive_json()
    assert fake.closed is True


def test_stt_releases_the_connection_slot_on_failure(auth_client: TestClient) -> None:
    with patch("backend.api.v1.chat.ws_tracker") as tracker:
        tracker.acquire = AsyncMock(return_value=True)
        tracker.release = AsyncMock()
        with patch("backend.services.oci_speech.STTClient") as factory:
            factory.side_effect = RuntimeError("no OCI quota")
            with pytest.raises(WebSocketDisconnect):
                with auth_client.websocket_connect("/api/stt/stream") as websocket:
                    websocket.receive_json()
    tracker.release.assert_awaited_once()


def test_stt_allows_a_configured_origin(auth_client: TestClient) -> None:
    fake = _FakeOciSttClient([{"text": "ok", "isFinal": True}])
    with patch("backend.services.oci_speech.STTClient", _stt_factory(fake)):
        with auth_client.websocket_connect(
            "/api/stt/stream", headers={"origin": "http://localhost:5173"}
        ) as websocket:
            assert websocket.receive_json() == {"text": "ok", "isFinal": True}
            websocket.send_bytes(b"")


def test_stt_resolves_the_websocket_session_cookie_name(
    auth_client: TestClient,
) -> None:
    from backend.core import auth

    assert auth._session_cookie_name() in auth_client.cookies
