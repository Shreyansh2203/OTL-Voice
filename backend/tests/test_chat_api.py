"""Chat streaming context, speech synthesis, and the STT WebSocket session."""

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
    """
    catalogue = _catalogue_mock()
    catalogue.alist_assignments_for_worker = AsyncMock(return_value=None)

    with (
        patch("backend.api.v1.chat.fusion_catalogue", catalogue),
        patch("backend.api.v1.chat.chat.build_system_prompt") as build_prompt,
    ):
        response = auth_client.post("/api/chat", json=_messages("log 8 hours"))

    assert response.status_code == 503
    build_prompt.assert_not_called()


def test_chat_still_answers_when_the_employee_really_has_no_assignments(
    auth_client: TestClient, mock_otl_client: MagicMock
) -> None:
    # [] is the genuine empty case and has to keep working: refusing it would turn a
    # missing-catalogue failure into an outage for employees who have no projects.
    catalogue = _catalogue_mock()

    with (
        patch("backend.api.v1.chat.fusion_catalogue", catalogue),
        patch("backend.api.v1.chat.chat.build_system_prompt", return_value="prompt"),
        patch("backend.services.chat.stream_sse") as stream,
    ):
        stream.return_value = iter(["data: ok\n\n"])
        response = auth_client.post("/api/chat", json=_messages("hello"))

    assert response.status_code == 200


def test_chat_adds_the_most_recent_timecard_to_the_prompt(
    auth_client: TestClient, mock_otl_client: MagicMock
) -> None:
    mock_otl_client.alist_timecard_entries.return_value = {
        "items": [
            {
                "measure": "7.5",
                "timeRecordEventAttribute": [
                    {"attributeName": "Comment", "attributeValue": "ignored"},
                    {"attributeName": "PJC_PROJECT_ID", "attributeValue": "P-9"},
                ],
            }
        ]
    }
    captured: dict[str, Any] = {}

    def _build(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "system prompt"

    catalogue = _catalogue_mock(
        get_project_by_id=MagicMock(
            return_value={"project_name": "Apollo", "project_number": "P-9"}
        )
    )
    with (
        patch("backend.api.v1.chat.chat.build_system_prompt", side_effect=_build),
        patch("backend.api.v1.chat.fusion_catalogue", catalogue),
        patch("backend.services.chat.stream_sse") as stream,
    ):
        stream.return_value = iter(["data: ok\n\n"])
        response = auth_client.post("/api/chat", json=_messages("hello"))
    assert response.status_code == 200
    assert captured["recent_history"] == (
        "User recently logged 7.5 hours on Apollo (Project P-9)."
    )
    assert catalogue.get_project_by_id.call_args.args == ("P-9",)


def test_chat_reads_the_legacy_time_attributes_shape(
    auth_client: TestClient, mock_otl_client: MagicMock
) -> None:
    mock_otl_client.alist_timecard_entries.return_value = {
        "items": [
            {
                "measure": "1",
                "timeAttributes": [
                    {"attributeName": "PJC_PROJECT_ID", "attributeValue": "P-1"}
                ],
            }
        ]
    }
    captured: dict[str, Any] = {}
    catalogue = _catalogue_mock(get_project_by_id=MagicMock(return_value=None))
    with (
        patch(
            "backend.api.v1.chat.chat.build_system_prompt",
            side_effect=lambda **kwargs: captured.update(kwargs) or "system prompt",
        ),
        patch("backend.api.v1.chat.fusion_catalogue", catalogue),
        patch("backend.services.chat.stream_sse") as stream,
    ):
        stream.return_value = iter([])
        auth_client.post("/api/chat", json=_messages("hello"))
    assert captured["recent_history"] == ""


def test_chat_survives_a_failing_recent_history_lookup(
    auth_client: TestClient, mock_otl_client: MagicMock
) -> None:
    mock_otl_client.alist_timecard_entries.side_effect = RuntimeError("fusion down")
    captured: dict[str, Any] = {}

    with (
        patch(
            "backend.api.v1.chat.chat.build_system_prompt",
            side_effect=lambda **kwargs: captured.update(kwargs) or "system prompt",
        ),
        patch("backend.services.chat.stream_sse") as stream,
    ):
        stream.return_value = iter(["data: ok\n\n"])
        response = auth_client.post("/api/chat", json=_messages("hello"))
    assert response.status_code == 200
    assert captured["recent_history"] == ""
    captured["streamed"] = response.text
    assert "ok" in captured["streamed"]


def test_chat_sets_no_buffer_headers(auth_client: TestClient) -> None:
    with patch("backend.services.chat.stream_sse") as stream:
        stream.return_value = iter([])
        response = auth_client.post("/api/chat", json=_messages("hello"))
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
    assert response.headers["content-type"].startswith("text/event-stream")


def test_tts_returns_synthesized_audio(auth_client: TestClient) -> None:
    response = auth_client.post("/api/tts", json={"text": "hello"})
    assert response.status_code == 200
    assert response.content == b"audio"
    assert response.headers["content-type"].startswith("audio/wav")


def test_tts_reports_an_unavailable_synthesizer(auth_client: TestClient) -> None:
    with patch("backend.api.v1.chat._speech_client") as factory:
        factory.return_value.synthesize.side_effect = RuntimeError("no quota")
        response = auth_client.post("/api/tts", json={"text": "hello"})
    assert response.status_code == 503
    assert "unavailable" in response.json()["detail"].lower()
    assert "no quota" not in response.text


def test_tts_never_leaks_oci_tenancy_detail(auth_client: TestClient) -> None:
    leaked = (
        "endpoint https://text-oc1.iam.us-ashburn-1.oci.oraclecloud.com "
        "key ocid1.apikey.oc1..secret tenancy ocid1.tenancy.oc1..real"
    )
    with patch("backend.api.v1.chat._speech_client") as factory:
        factory.return_value.synthesize.side_effect = RuntimeError(leaked)
        response = auth_client.post("/api/tts", json={"text": "hello"})
    assert response.status_code == 503
    body = response.text
    assert "ocid1" not in body
    assert "oci.oraclecloud.com" not in body
    assert "us-ashburn-1" not in body


def test_tts_requires_authentication(client: TestClient) -> None:
    assert client.post("/api/tts", json={"text": "hello"}).status_code == 401


class _FakeOciSttClient:
    def __init__(self, results: list[dict[str, Any]], prefill: int = 0) -> None:
        self._results = results
        self._prefill = prefill
        self.sent: list[bytes] = []
        self.final_requested = False
        self.closed = False
        self.queue: asyncio.Queue | None = None

    async def stream_session(self) -> tuple[Any, asyncio.Queue, asyncio.Event, Any]:
        self.queue = asyncio.Queue(maxsize=100)
        for index in range(self._prefill):
            self.queue.put_nowait({"text": f"prefill-{index}", "isFinal": False})
        for result in self._results:
            self.queue.put_nowait(result)
        done = asyncio.Event()
        loop = asyncio.create_task(asyncio.sleep(30))
        return self, self.queue, done, loop

    async def send_data(self, data: bytes) -> None:
        self.sent.append(data)

    async def request_final_result(self) -> None:
        self.final_requested = True

    async def close(self) -> None:
        self.closed = True


def _stt_factory(fake: Any) -> MagicMock:
    """A STTClient replacement whose instances are `fake`."""
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
