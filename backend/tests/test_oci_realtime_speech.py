"""The vendored OCI realtime speech websocket client."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest
from oci.ai_speech.models import (
    RealtimeMessage,
    RealtimeMessageSendFinalResult,
    RealtimeParameters,
)
from websockets.exceptions import ConnectionClosed
from websockets.frames import Close

from backend.core.oci_ai_speech_realtime import (
    RealtimeSpeechClient,
    RealtimeSpeechClientListener,
)
from backend.core.oci_ai_speech_realtime import (
    ai_service_speech_realtime_client as client_module,
)

CONFIG = {
    "tenancy": "ocid1.tenancy.oc1..test",
    "user": "ocid1.user.oc1..test",
    "fingerprint": "aa:bb:cc",
    "region": "us-ashburn-1",
    "key_file": "/run/secrets/oci.pem",
}


class _Listener:
    def __init__(self) -> None:
        self.events: list[tuple[str, Any]] = []
        self.connected = 0
        self.closed: list[tuple[int, str]] = []

    def on_connect(self) -> None:
        self.connected += 1

    def on_connect_message(self, message: Any) -> None:
        self.events.append(("connect", message))

    def on_ack_message(self, message: Any) -> None:
        self.events.append(("ack", message))

    def on_result(self, message: Any) -> None:
        self.events.append(("result", message))

    def on_error(self, message: Any) -> None:
        self.events.append(("error", message))

    def on_network_event(self, message: Any) -> None:
        self.events.append(("network", message))

    def on_close(self, error_code: int, error_message: str) -> None:
        self.closed.append((error_code, error_message))

    def kinds(self) -> list[str]:
        return [kind for kind, _ in self.events]


class _Socket:
    def __init__(self, incoming: list[Any]) -> None:
        self._incoming = list(incoming)
        self.sent: list[Any] = []
        self.closed = False

    async def send(self, data: Any) -> None:
        self.sent.append(data)

    async def recv(self) -> Any:
        if not self._incoming:
            raise _closed(1006, "abnormal closure")
        nxt = self._incoming.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    async def close(self) -> None:
        self.closed = True


def _closed(code: int, reason: str) -> ConnectionClosed:
    return ConnectionClosed(rcvd=Close(code, reason), sent=None)


class _FalsyListener(_Listener):
    """Stands in for the ``if self.listener`` guard being false."""

    def __bool__(self) -> bool:
        return False


def _signed_signer() -> Any:
    signer = MagicMock()
    signer._basic_signer.sign.return_value = {
        "date": "Thu, 01 Jan 2026 00:00:00 GMT",
        "authorization": "Signature version=1",
    }
    return signer


class _ConnectScript:
    def __init__(self) -> None:
        self.scripts: list[list[Any]] = []
        self.sockets: list[_Socket] = []


@pytest.fixture(autouse=True)
def skip_oci_config_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client_module, "validate_config", lambda *a, **k: None)


@pytest.fixture
def connect_script(monkeypatch: pytest.MonkeyPatch) -> _ConnectScript:
    """Patches websockets.connect; queue the frames each connection should see."""
    script = _ConnectScript()

    def _connect(uri: str, **kwargs: Any) -> Any:
        socket = _Socket(script.scripts.pop(0) if script.scripts else [])
        script.sockets.append(socket)
        return _AsyncContextManager(socket)

    monkeypatch.setattr(client_module.websockets, "connect", _connect, raising=False)
    return script


class _AsyncContextManager:
    def __init__(self, socket: _Socket) -> None:
        self.socket = socket

    async def __aenter__(self) -> _Socket:
        return self.socket

    async def __aexit__(self, *args: Any) -> bool:
        return False


def _client(
    listener: Any = None,
    signer: Any = None,
    parameters: RealtimeParameters | None = None,
) -> RealtimeSpeechClient:
    return RealtimeSpeechClient(
        config=CONFIG,
        realtime_speech_parameters=parameters,
        listener=listener,
        service_endpoint="wss://realtime.aiservice.us-ashburn-1.oci.oraclecloud.com",
        signer=signer or _signed_signer(),
        compartment_id="ocid1.compartment.oc1..test",
    )


def test_default_parameters_are_built_when_none_are_supplied() -> None:
    client = _client()
    params = client.realtime_speech_parameters
    assert params.encoding == "audio/raw;rate=16000"
    assert params.language_code == "en-US"
    assert params.model_type == "ORACLE"
    assert params.model_domain == RealtimeParameters.MODEL_DOMAIN_GENERIC
    assert params.final_silence_threshold_in_ms == 2000
    assert params.partial_silence_threshold_in_ms == 0
    assert params.is_ack_enabled is False
    assert params.punctuation == RealtimeParameters.PUNCTUATION_NONE
    assert params.stabilize_partial_results == (
        RealtimeParameters.STABILIZE_PARTIAL_RESULTS_NONE
    )
    assert params.should_ignore_invalid_customizations is False
    assert params.customizations == []
    assert client.compartment_id == "ocid1.compartment.oc1..test"
    assert client.close_flag is False
    assert client.connection is None


def test_uri_carries_the_serialised_parameters() -> None:
    uri = _client().uri
    assert uri.startswith("wss://realtime.aiservice.us-ashburn-1.oci.oraclecloud.com")
    assert "/ws/transcribe/stream?" in uri
    assert "languageCode=en-US" in uri
    assert "encoding=audio/raw;rate=16000" in uri
    assert not uri.endswith("&")


def test_supplied_parameters_are_used_verbatim() -> None:
    params = RealtimeParameters()
    params.language_code = "de-DE"
    params.is_ack_enabled = True
    params.punctuation = "AUTO"
    params.model_type = "CUSTOM"
    params.customizations = [{"name": "keyword", "value": "otl"}]
    client = _client(parameters=params)
    assert client.realtime_speech_parameters is params
    assert "isAckEnabled=true" in client.uri
    assert "languageCode=de-DE" in client.uri
    assert "punctuation=AUTO" in client.uri
    assert "modelType=CUSTOM" in client.uri
    assert "customizations=" in client.uri
    assert "%5B%7B%22name%22" in client.uri


def test_model_type_oracle_is_omitted_from_the_query() -> None:
    params = RealtimeParameters()
    params.language_code = "en-US"
    params.model_type = "ORACLE"
    params.punctuation = RealtimeParameters.PUNCTUATION_NONE
    params.is_ack_enabled = None
    params.should_ignore_invalid_customizations = None
    params.partial_silence_threshold_in_ms = None
    params.final_silence_threshold_in_ms = None
    params.stabilize_partial_results = None
    params.customizations = None
    assert "modelType" not in _client(parameters=params).uri
    assert "punctuation" not in _client(parameters=params).uri
    assert _client(parameters=params).uri.endswith("languageCode=en-US")


def test_service_endpoint_is_derived_from_the_region(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(client_module, "validate_config", lambda *a, **k: None)
    monkeypatch.setattr(client_module, "Signer", lambda **kwargs: "signer")
    client = RealtimeSpeechClient(
        config=CONFIG,
        signer="signer",
        compartment_id="ocid1.compartment.oc1..test",
    )
    assert client.service_endpoint == (
        "wss://realtime.aiservice.us-ashburn-1.oci.oraclecloud.com"
    )


def test_missing_region_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client_module, "validate_config", lambda *a, **k: None)
    monkeypatch.setattr(client_module, "Signer", lambda **kwargs: "signer")
    with pytest.raises(ValueError, match="Region not found in config"):
        RealtimeSpeechClient(
            config={"tenancy": "t", "user": "u", "fingerprint": "f"},
            signer="signer",
            compartment_id="c",
        )


def test_signer_is_built_from_config_when_not_supplied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(client_module, "validate_config", lambda *a, **k: None)
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        client_module, "Signer", lambda **kwargs: captured.update(kwargs) or "signer"
    )
    client = RealtimeSpeechClient(config=CONFIG, compartment_id="c")
    assert client.signer == "signer"
    assert captured["tenancy"] == CONFIG["tenancy"]
    assert captured["private_key_file_location"] == "/run/secrets/oci.pem"
    assert "pass_phrase" in captured


def test_signer_is_built_from_the_authentication_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = dict(CONFIG) | {"authentication_type": "resource_principal"}
    monkeypatch.setattr(
        client_module,
        "get_signer_from_authentication_type",
        lambda value: f"signer-for-{value['authentication_type']}",
    )
    client = RealtimeSpeechClient(config=config, compartment_id="c")
    assert client.signer == "signer-for-resource_principal"


@pytest.mark.asyncio
async def test_connect_sends_credentials_then_dispatches_events(
    connect_script: _ConnectScript,
) -> None:
    connect_script.scripts.append(
        [
            json.dumps({"event": RealtimeMessage.EVENT_CONNECT}),
            json.dumps({"event": RealtimeMessage.EVENT_ACKAUDIO, "id": 1}),
            json.dumps({"event": RealtimeMessage.EVENT_RESULT, "transcriptions": []}),
            json.dumps({"event": RealtimeMessage.EVENT_ERROR, "message": "bad"}),
        ]
    )
    listener = _Listener()
    client = _client(listener=listener)
    await client.connect()

    assert listener.connected == 1
    assert listener.kinds() == ["connect", "ack", "result", "error"]
    credentials = json.loads(connect_script.sockets[0].sent[0])
    assert credentials["authenticationType"] == "CREDENTIALS"
    assert credentials["compartmentId"] == "ocid1.compartment.oc1..test"
    assert credentials["headers"]["authorization"] == "Signature version=1"
    assert credentials["headers"]["uri"] == client.uri
    assert client.close_flag is True


@pytest.mark.asyncio
async def test_connect_stops_when_the_socket_drains(
    connect_script: _ConnectScript,
) -> None:
    listener = _Listener()
    client = _client(listener=listener)
    await client.connect()
    assert listener.closed == [(1006, "abnormal closure")]
    assert connect_script.sockets[0].sent[0].startswith("{")


@pytest.mark.asyncio
async def test_credentials_are_signed_for_the_stream_path(
    connect_script: _ConnectScript,
) -> None:
    signer = _signed_signer()
    client = _client(listener=_Listener(), signer=signer)
    await client.connect()
    _, kwargs = signer._basic_signer.sign.call_args
    assert kwargs["host"] == "realtime.aiservice.us-ashburn-1.oci.oraclecloud.com"
    assert kwargs["method"] == "GET"
    assert kwargs["path"].startswith("/ws/transcribe/stream?")


@pytest.mark.asyncio
async def test_send_data_and_final_result_track_the_connection() -> None:
    client = _client()
    await client.send_data(b"ignored")
    await client.request_final_result()

    socket = _Socket([])
    client.connection = socket  # type: ignore[assignment]
    await client.send_data(b"pcm")
    await client.request_final_result()
    assert socket.sent == [b"pcm", str(RealtimeMessageSendFinalResult())]


def test_on_close_reports_and_clears_the_connection() -> None:
    listener = _Listener()
    client = _client(listener=listener)
    client.connection = _Socket([])  # type: ignore[assignment]
    client.on_close(1006, "abnormal")
    assert listener.closed == [(1006, "abnormal")]
    assert client.close_flag is True
    assert client.connection is None


@pytest.mark.asyncio
async def test_handle_messages_survives_a_malformed_frame() -> None:
    listener = _Listener()
    client = _client(listener=listener)
    socket = _Socket(["not json at all", json.dumps({"event": "UNKNOWN"})])
    await client._handle_messages(socket)
    assert listener.events == []


@pytest.mark.asyncio
async def test_handle_messages_reports_a_closed_connection() -> None:
    listener = _Listener()
    client = _client(listener=listener)
    await client._handle_messages(_Socket([]))
    assert listener.closed == [(1006, "abnormal closure")]
    assert client.close_flag is True


@pytest.mark.asyncio
async def test_handle_messages_ignores_events_without_a_listener() -> None:
    listener = _FalsyListener()
    client = _client(listener=listener)
    await client._handle_messages(
        _Socket(
            [
                json.dumps({"event": RealtimeMessage.EVENT_RESULT}),
                json.dumps({"event": RealtimeMessage.EVENT_ACKAUDIO}),
                json.dumps({"event": RealtimeMessage.EVENT_CONNECT}),
                json.dumps({"event": RealtimeMessage.EVENT_ERROR}),
            ]
        )
    )
    assert listener.events == []
    assert listener.closed == [(1006, "abnormal closure")]


@pytest.mark.asyncio
async def test_close_is_safe_with_and_without_a_connection() -> None:
    listener = _Listener()
    client = _client(listener=listener)
    await client.close()
    assert listener.closed == [(1000, "Closure Initiated by Client")]

    socket = _Socket([])
    client = _client(listener=listener)
    client.connection = socket  # type: ignore[assignment]
    await client.close()
    assert socket.closed is True
    assert client.connection is None
    assert client.close_flag is True


@pytest.mark.asyncio
async def test_close_tolerates_a_failing_socket() -> None:
    class _Angry(_Socket):
        async def close(self) -> None:
            raise OSError("already gone")

    listener = _Listener()
    client = _client(listener=listener)
    client.connection = _Angry([])  # type: ignore[assignment]
    await client.close()
    assert listener.closed == [(1000, "Closure Initiated by Client")]


@pytest.mark.asyncio
async def test_close_without_a_listener_still_clears_state() -> None:
    client = _client(listener=None)
    await client.close()
    assert client.close_flag is True


def test_listener_protocol_recognises_a_complete_implementation() -> None:
    class Complete:
        def on_network_event(self, message: Any) -> None: ...

        def on_ack_message(self, message: Any) -> None: ...

        def on_connect_message(self, message: Any) -> None: ...

        def on_connect(self) -> None: ...

        def on_error(self, message: Any) -> None: ...

        def on_result(self, message: Any) -> None: ...

    class Missing:
        def on_network_event(self, message: Any) -> None: ...

        def on_ack_message(self, message: Any) -> None: ...

        def on_connect_message(self, message: Any) -> None: ...

        def on_connect(self) -> None: ...

        def on_error(self, message: Any) -> None: ...

    assert issubclass(Complete, RealtimeSpeechClientListener)
    assert not issubclass(Missing, RealtimeSpeechClientListener)
    assert not issubclass(object, RealtimeSpeechClientListener)
