"""Speech payload construction, realtime STT setup, and the STT listener."""

from __future__ import annotations

import asyncio
from typing import Any

import oci
import pytest

from backend.services import oci_speech
from backend.services.oci_speech import SpeechClient, STTClient

OCI_CONFIG = {
    "user": "ocid1.user.oc1..test",
    "tenancy": "ocid1.tenancy.oc1..test",
    "fingerprint": "aa:bb:cc",
    "region": "us-ashburn-1",
    "key_file": "/run/secrets/oci.pem",
}


class _Body:
    def __init__(self, content: bytes | None) -> None:
        self.content = content


class _SynthesizeResponse:
    def __init__(self, body: Any) -> None:
        self.data = body


def _service_error() -> oci.exceptions.ServiceError:
    return oci.exceptions.ServiceError(
        status=500, code="500", message="error", headers={}
    )


def _recording_client(calls: list[Any], fail_on_ssml: bool = False) -> Any:
    def _synthesize(_self: Any, details: Any) -> _SynthesizeResponse:
        calls.append(details)
        if fail_on_ssml and details.configuration.speech_settings.text_type == "SSML":
            raise _service_error()
        return _SynthesizeResponse(_Body(b"audio"))

    return type("C", (), {"synthesize_speech": _synthesize})()


class _FakeRealtimeParameters:
    MODEL_DOMAIN_GENERIC = "GENERIC"
    PUNCTUATION_AUTO = "AUTO"
    STABILIZE_PARTIAL_RESULTS_MEDIUM = "MEDIUM"

    def __init__(self) -> None:
        self.language_code = ""
        self.model_domain = ""
        self.encoding = ""
        self.partial_silence_threshold_in_ms = 0
        self.final_silence_threshold_in_ms = 0
        self.punctuation = ""
        self.stabilize_partial_results = ""


@pytest.fixture
def speech(monkeypatch: pytest.MonkeyPatch) -> SpeechClient:
    monkeypatch.setenv("OCI_COMPARTMENT_ID", "ocid1.compartment.oc1..test")
    monkeypatch.setenv("TTS_MODEL_NAME", "TTS_2_NATURAL")
    monkeypatch.setenv("TTS_LANGUAGE_CODE", "en-US")
    monkeypatch.setenv("TTS_SAMPLE_RATE", "22050")
    monkeypatch.setenv("TTS_OUTPUT_FORMAT", "MP3")
    monkeypatch.setattr(oci_speech, "build_oci_config", lambda: dict(OCI_CONFIG))
    monkeypatch.setattr(oci_speech, "AIServiceSpeechClient", lambda **kwargs: kwargs)
    return SpeechClient()


def test_speech_region_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OCI_COMPARTMENT_ID", "ocid1.compartment.oc1..test")
    monkeypatch.setattr(oci_speech, "build_oci_config", lambda: dict(OCI_CONFIG))
    monkeypatch.setattr(oci_speech, "AIServiceSpeechClient", lambda **kwargs: kwargs)
    monkeypatch.delenv("OCI_SPEECH_REGION", raising=False)
    assert SpeechClient().region == "us-ashburn-1"
    monkeypatch.setenv("OCI_SPEECH_REGION", "eu-dublin-1")
    assert SpeechClient().region == "eu-dublin-1"
    monkeypatch.delenv("OCI_SPEECH_REGION")
    monkeypatch.setattr(oci_speech, "build_oci_config", lambda: {})
    monkeypatch.setenv("OCI_REGION", "ap-mumbai-1")
    assert SpeechClient().region == "ap-mumbai-1"


def test_speech_client_is_constructed_with_a_bounded_retry_and_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OCI_COMPARTMENT_ID", "ocid1.compartment.oc1..test")
    monkeypatch.setenv("REQUEST_TIMEOUT_SECONDS", "42")
    monkeypatch.setattr(oci_speech, "build_oci_config", lambda: dict(OCI_CONFIG))
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        oci_speech,
        "AIServiceSpeechClient",
        lambda **kwargs: captured.update(kwargs) or kwargs,
    )
    SpeechClient()
    assert captured["service_endpoint"].endswith("us-ashburn-1.oci.oraclecloud.com")
    assert captured["timeout"] == (10, 42)
    assert isinstance(captured["retry_strategy"], oci.retry.NoneRetryStrategy)


def test_details_uses_the_matching_model_family(speech: SpeechClient) -> None:
    natural = speech._details("hello", "TEXT")
    assert natural.text == "hello"
    assert natural.configuration.model_family == "ORACLE"
    assert natural.configuration.model_details.model_name == "TTS_2_NATURAL"
    assert natural.configuration.model_details.language_code == "en-US"
    assert natural.configuration.speech_settings.sample_rate_in_hz == 22050
    assert natural.configuration.speech_settings.speech_mark_types == []
    assert natural.is_stream_enabled is False

    speech.model_name = "TTS_1_STANDARD"
    standard = speech._details("hello", "SSML")
    assert standard.configuration.model_details.model_name == "TTS_1_STANDARD"
    assert not hasattr(standard.configuration.model_details, "language_code")
    assert standard.configuration.speech_settings.text_type == "SSML"


def test_rate_change_wraps_plain_text_in_escaped_prosody(speech: SpeechClient) -> None:
    calls: list[Any] = []
    speech.client = _recording_client(calls)
    assert speech.synthesize("Log <four> & hours", 1.5) == b"audio"
    assert calls[0].configuration.speech_settings.text_type == "SSML"
    assert calls[0].text == (
        '<speak><prosody rate="150%">Log &lt;four&gt; &amp; hours</prosody></speak>'
    )


def test_user_supplied_ssml_is_preserved(speech: SpeechClient) -> None:
    calls: list[Any] = []
    speech.client = _recording_client(calls)
    assert speech.synthesize('Log <break time="500ms"/> hours', 1.0) == b"audio"
    assert calls[0].configuration.speech_settings.text_type == "SSML"
    assert calls[0].text == '<speak>Log <break time="500ms"/> hours</speak>'


def test_ssml_with_a_rate_uses_prosody_around_the_existing_markup(
    speech: SpeechClient,
) -> None:
    calls: list[Any] = []
    speech.client = _recording_client(calls)
    assert speech.synthesize("Logged <emphasis>four</emphasis> hours", 2.0) == b"audio"
    assert calls[0].text == (
        '<speak><prosody rate="200%">Logged <emphasis>four</emphasis> hours</prosody></speak>'
    )


@pytest.fixture
def single_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    # The production call path retries with backoff; these tests assert the
    # payload and the fallback, so collapsing the retry keeps them fast.
    monkeypatch.setattr(
        oci_speech, "_retry_with_backoff", lambda func, **_kwargs: func()
    )


def test_rejected_ssml_falls_back_to_stripped_text(
    speech: SpeechClient, single_attempt: None
) -> None:
    calls: list[Any] = []
    speech.client = _recording_client(calls, fail_on_ssml=True)
    assert speech.synthesize("Logged <emphasis>four</emphasis> hours", 1.0) == b"audio"
    assert calls[0].configuration.speech_settings.text_type == "SSML"
    assert calls[-1].configuration.speech_settings.text_type == "TEXT"
    assert calls[-1].text == "Logged four hours"


def test_rejected_prosody_falls_back_to_stripped_text(
    speech: SpeechClient, single_attempt: None
) -> None:
    calls: list[Any] = []
    speech.client = _recording_client(calls, fail_on_ssml=True)
    assert speech.synthesize("Logged four hours", 1.5) == b"audio"
    assert calls[0].configuration.speech_settings.text_type == "SSML"
    assert calls[-1].configuration.speech_settings.text_type == "TEXT"
    assert calls[-1].text == "Logged four hours"


def test_stt_client_requires_a_compartment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OCI_COMPARTMENT_ID", raising=False)
    monkeypatch.setattr(oci_speech, "build_oci_config", lambda: dict(OCI_CONFIG))
    with pytest.raises(RuntimeError, match="OCI_COMPARTMENT_ID"):
        STTClient()


def test_stt_client_builds_a_signer_from_a_key_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OCI_COMPARTMENT_ID", "ocid1.compartment.oc1..test")
    monkeypatch.setattr(oci_speech, "build_oci_config", lambda: dict(OCI_CONFIG))
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        "oci.signer.Signer", lambda **kwargs: captured.update(kwargs) or "signer"
    )
    assert STTClient()._authenticator() == "signer"
    assert captured["private_key_file_location"] == "/run/secrets/oci.pem"
    assert "private_key_content" not in captured


def test_stt_client_builds_a_signer_from_inline_key_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = dict(OCI_CONFIG) | {"key_content": "-----BEGIN PRIVATE KEY-----"}
    monkeypatch.setenv("OCI_COMPARTMENT_ID", "ocid1.compartment.oc1..test")
    monkeypatch.setattr(oci_speech, "build_oci_config", lambda: config)
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        "oci.signer.Signer", lambda **kwargs: captured.update(kwargs) or "signer"
    )
    assert STTClient()._authenticator() == "signer"
    assert captured["private_key_file_location"] is None
    assert captured["private_key_content"] == "-----BEGIN PRIVATE KEY-----"


def _stt_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OCI_COMPARTMENT_ID", "ocid1.compartment.oc1..test")
    monkeypatch.setattr(oci_speech, "build_oci_config", lambda: dict(OCI_CONFIG))
    monkeypatch.setattr(oci_speech, "RealtimeParameters", _FakeRealtimeParameters)
    monkeypatch.setattr("oci.signer.Signer", lambda **kwargs: "signer")


@pytest.mark.asyncio
async def test_stream_session_returns_a_connected_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stt_env(monkeypatch)
    connected: list[str] = []

    class _Client:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs
            self.params = kwargs["realtime_speech_parameters"]

        async def connect(self) -> None:
            connected.append(self.kwargs["service_endpoint"])
            self.kwargs["listener"].connected.set()

        async def close(self) -> None:
            return None

    monkeypatch.setattr(oci_speech, "RealtimeSpeechClient", _Client)
    client, result_queue, done, loop_task = await STTClient().stream_session()
    assert connected == ["wss://realtime.aiservice.us-ashburn-1.oci.oraclecloud.com"]
    assert result_queue.maxsize == 100
    assert isinstance(done, asyncio.Event)
    assert client.params.encoding == "audio/raw;rate=16000"
    assert client.params.final_silence_threshold_in_ms == 2000
    assert client.params.partial_silence_threshold_in_ms == 0
    assert client.params.punctuation == _FakeRealtimeParameters.PUNCTUATION_AUTO
    assert client.kwargs["compartment_id"] == "ocid1.compartment.oc1..test"
    await loop_task


@pytest.mark.asyncio
async def test_stream_session_raises_when_the_listener_never_connects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stt_env(monkeypatch)
    closed: list[bool] = []

    class _Client:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

        async def connect(self) -> None:
            # The service never opens the stream, so it ends the session
            # instead of leaving the production 10s connect wait in the test.
            self.kwargs["listener"].done.set()
            await asyncio.sleep(30)

        async def close(self) -> None:
            closed.append(True)

    monkeypatch.setattr(oci_speech, "RealtimeSpeechClient", _Client)
    with pytest.raises(RuntimeError, match="Failed to connect STT listener"):
        await STTClient().stream_session()
    assert closed == [True]


@pytest.mark.asyncio
async def test_stream_session_surfaces_a_connect_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stt_env(monkeypatch)

    class _Client:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

        async def connect(self) -> None:
            # End the session only once the connect task has actually failed,
            # which is the ordering stream_session relies on to re-raise the
            # underlying error instead of the generic connect timeout.
            task = asyncio.current_task()
            assert task is not None
            task.add_done_callback(lambda _t: self.kwargs["listener"].done.set())
            raise OSError("dns failure")

        async def close(self) -> None:
            return None

    monkeypatch.setattr(oci_speech, "RealtimeSpeechClient", _Client)
    with pytest.raises(OSError, match="dns failure"):
        await STTClient().stream_session()


@pytest.mark.asyncio
async def test_stream_session_requires_the_realtime_sdk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stt_env(monkeypatch)
    monkeypatch.delattr(oci_speech, "RealtimeParameters", raising=False)
    with pytest.raises(RuntimeError, match="Realtime SDK is not available"):
        await STTClient().stream_session()


def _listener() -> Any:
    return oci_speech._STTListener(asyncio.Queue())


def test_listener_forwards_final_transcriptions() -> None:
    listener = _listener()
    listener.on_result(
        {"transcriptions": [{"transcription": " logged ", "isFinal": True}]}
    )
    assert listener.result_queue.get_nowait() == {"text": "logged", "isFinal": True}


def test_listener_forwards_partial_transcriptions() -> None:
    listener = _listener()
    listener.on_result({"transcriptions": [{"transcription": "log", "isFinal": False}]})
    assert listener.result_queue.get_nowait() == {"text": "log", "isFinal": False}


@pytest.mark.parametrize("text", ["", "   ", ".", ",", "?", "!", "...", "-", "\u2013"])
def test_listener_drops_punctuation_only_transcriptions(text: str) -> None:
    listener = _listener()
    listener.on_result({"transcriptions": [{"transcription": text}]})
    assert listener.result_queue.empty()


def test_listener_ignores_empty_transcript_lists() -> None:
    listener = _listener()
    listener.on_result({})
    listener.on_result({"transcriptions": []})
    assert listener.result_queue.empty()


def test_listener_drops_transcriptions_when_the_queue_is_full() -> None:
    queue: asyncio.Queue = asyncio.Queue(maxsize=1)
    queue.put_nowait({"text": "first", "isFinal": True})
    listener = oci_speech._STTListener(queue)
    listener.on_result({"transcriptions": [{"transcription": "second"}]})
    assert queue.get_nowait() == {"text": "first", "isFinal": True}


def test_listener_signals_connect_error_and_close() -> None:
    listener = _listener()
    assert listener.connected.is_set() is False
    assert listener.done.is_set() is False
    listener.on_connect()
    assert listener.connected.is_set() is True
    listener.on_connect_message({})
    listener.on_ack_message({})
    listener.on_network_event({})
    assert listener.done.is_set() is False
    listener.on_error({"message": "bad request"})
    assert listener.done.is_set() is True


def test_listener_signals_done_on_close() -> None:
    listener = _listener()
    listener.on_close(1000, "bye")
    assert listener.done.is_set() is True
