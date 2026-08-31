from __future__ import annotations

import re
from typing import TypeVar
from xml.sax.saxutils import escape

import oci
from oci.ai_speech import AIServiceSpeechClient
from oci.ai_speech import models as speech_models

from .oci_gemini import _env, _retry_with_backoff, build_oci_config

T = TypeVar("T")


def _speech_endpoint(region: str) -> str:
    explicit = _env("OCI_SPEECH_ENDPOINT")
    if explicit:
        return explicit
    return f"https://speech.aiservice.{region}.oci.oraclecloud.com"


def _rate_to_percent(rate: float) -> str:
    pct = round(max(0.2, min(3.0, rate)) * 100)
    return f"{pct}%"


_CODE_FENCE = re.compile(r"```.*?```", re.DOTALL)
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_INLINE_CODE = re.compile(r"`([^`]+)`")
_STRIKE = re.compile(r"~~([^~]+)~~")
_HR = re.compile(r"^\s{0,3}([-*_])(?:\s*\1){2,}\s*$", re.MULTILINE)
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)
_BLOCKQUOTE = re.compile(r"^\s{0,3}>\s?", re.MULTILINE)
_BULLET = re.compile(r"^\s{0,3}[-*+]\s+", re.MULTILINE)
_STAR_EMPH = re.compile(r"\*{1,3}([^*]+?)\*{1,3}")
_US_EMPH = re.compile(r"(?<!\w)_{1,3}([^_]+?)_{1,3}(?!\w)")
_MULTISPACE = re.compile(r"[ \t]+")
_MULTINEWLINE = re.compile(r"\n\s*\n+")


def clean_for_speech(text: str) -> str:
    if not text:
        return ""
    t = _CODE_FENCE.sub(" ", text)
    t = _MD_LINK.sub(r"\1", t)
    t = _INLINE_CODE.sub(r"\1", t)
    t = _STRIKE.sub(r"\1", t)
    t = _HR.sub(" ", t)
    t = _HEADING.sub("", t)
    t = _BLOCKQUOTE.sub("", t)
    t = _BULLET.sub("", t)
    t = _STAR_EMPH.sub(r"\1", t)
    t = _US_EMPH.sub(r"\1", t)
    t = t.replace("**", " ").replace("*", " ")
    t = _MULTISPACE.sub(" ", t)
    t = _MULTINEWLINE.sub("\n", t)
    return t.strip()


class SpeechClient:
    def __init__(self) -> None:
        self.config = build_oci_config()
        self.region = self.config.get("region") or _env("OCI_REGION")
        self.compartment_id = _env("OCI_COMPARTMENT_ID")
        if not self.compartment_id:
            raise RuntimeError("OCI_COMPARTMENT_ID is not set in your .env.")
        self.voice_id = _env("TTS_VOICE_ID", "Brian")
        self.model_name = _env("TTS_MODEL_NAME", "TTS_2_NATURAL")
        self.language_code = _env("TTS_LANGUAGE_CODE", "en-US")
        self.sample_rate = int(_env("TTS_SAMPLE_RATE", "22050"))
        self.output_format = _env("TTS_OUTPUT_FORMAT", "MP3").upper()
        read_timeout = int(_env("REQUEST_TIMEOUT_SECONDS", "300"))
        self.client = AIServiceSpeechClient(
            config=self.config,
            service_endpoint=_speech_endpoint(self.region),
            retry_strategy=oci.retry.NoneRetryStrategy(),
            timeout=(10, read_timeout),
        )

    @property
    def mime(self) -> str:
        return {
            "MP3": "audio/mpeg",
            "OGG": "audio/ogg",
            "PCM": "audio/wav",
        }.get(self.output_format, "audio/mpeg")

    @property
    def signature(self) -> str:
        return ":".join(
            [
                self.voice_id,
                self.model_name,
                self.language_code,
                str(self.sample_rate),
                self.output_format,
            ]
        )

    def _details(
        self, text: str, text_type: str
    ) -> speech_models.SynthesizeSpeechDetails:
        model_details = speech_models.TtsOracleTts2NaturalModelDetails(
            model_name=self.model_name,
            voice_id=self.voice_id,
            language_code=self.language_code,
        )
        return speech_models.SynthesizeSpeechDetails(
            text=text,
            is_stream_enabled=False,
            compartment_id=self.compartment_id,
            configuration=speech_models.TtsOracleConfiguration(
                model_family="ORACLE",
                model_details=model_details,
                speech_settings=speech_models.TtsOracleSpeechSettings(
                    text_type=text_type,
                    sample_rate_in_hz=self.sample_rate,
                    output_format=self.output_format,
                    speech_mark_types=[],
                ),
            ),
        )

    def _call(self, details) -> bytes:
        def _do_call():
            response = self.client.synthesize_speech(details)
            data = response.data
            if hasattr(data, "content") and data.content is not None:
                return data.content
            return data.raw.read()

        return _retry_with_backoff(_do_call, max_retries=3, base_delay=1.0)

    def synthesize(self, text: str, rate: float = 1.0) -> bytes:
        clean = clean_for_speech(text)
        if not clean:
            return b""
        is_ssml = bool(
            re.search(
                r"<(?:break|emphasis|prosody)[^>]*>.*?</(?:break|emphasis|prosody)>|<(?:break|emphasis|prosody)[^>]*/>",
                clean,
                re.IGNORECASE,
            )
        )
        if is_ssml:
            ssml_payload = f"<speak>{clean}</speak>"
            if abs(rate - 1.0) > 1e-3:
                ssml_payload = f'<speak><prosody rate="{_rate_to_percent(rate)}">{clean}</prosody></speak>'
            try:
                import xml.etree.ElementTree as ET

                ET.fromstring(ssml_payload)
                return self._call(self._details(ssml_payload, "SSML"))
            except oci.exceptions.ServiceError:
                clean = re.sub(r"<[^>]+>", "", clean)
        if abs(rate - 1.0) < 1e-3:
            return self._call(self._details(clean, "TEXT"))
        ssml = (
            f'<speak><prosody rate="{_rate_to_percent(rate)}">'
            f"{escape(clean)}</prosody></speak>"
        )
        try:
            return self._call(self._details(ssml, "SSML"))
        except oci.exceptions.ServiceError:
            return self._call(self._details(clean, "TEXT"))


import asyncio

try:
    from oci.ai_speech.models import RealtimeParameters

    from backend.core.oci_ai_speech_realtime import (
        RealtimeSpeechClient,
        RealtimeSpeechClientListener,
    )

    class _STTListener(RealtimeSpeechClientListener):
        def __init__(self, result_queue: asyncio.Queue):
            self.result_queue = result_queue
            self.done = asyncio.Event()
            self.connected = asyncio.Event()

        def on_result(self, result):
            transcriptions = result.get("transcriptions", [])
            if transcriptions:
                tx = transcriptions[0]
                text = tx.get("transcription", "").strip()
                is_final = tx.get("isFinal", False)
                if text and text not in [".", ",", "?", "!", "...", "-", "–"]:
                    try:
                        self.result_queue.put_nowait(
                            {"text": text, "isFinal": is_final}
                        )
                    except asyncio.QueueFull:
                        print("OCI STT result_queue is full, dropping transcription.")

        def on_ack_message(self, ackmessage):
            pass

        def on_connect(self):
            self.connected.set()

        def on_connect_message(self, connectmessage):
            self.connected.set()

        def on_network_event(self, ackmessage):
            pass

        def on_error(self, error_message):
            self.done.set()

        def on_close(self, error_code, error_message):
            self.done.set()
except ImportError:

    class _DummySTTListener:
        pass

    _STTListener = _DummySTTListener  # type: ignore


class STTClient:
    def __init__(self) -> None:
        self.config = build_oci_config()
        self.region = self.config.get("region") or _env("OCI_REGION")
        self.compartment_id = _env("OCI_COMPARTMENT_ID")
        if not self.compartment_id:
            raise RuntimeError("OCI_COMPARTMENT_ID is not set in your .env.")

    def _authenticator(self):
        from oci.signer import Signer

        if "key_content" in self.config:
            return Signer(
                tenancy=self.config["tenancy"],
                user=self.config["user"],
                fingerprint=self.config["fingerprint"],
                private_key_file_location=None,
                private_key_content=self.config["key_content"],
                pass_phrase=self.config.get("pass_phrase"),
            )
        else:
            return Signer(
                tenancy=self.config["tenancy"],
                user=self.config["user"],
                fingerprint=self.config["fingerprint"],
                private_key_file_location=self.config.get("key_file"),
                pass_phrase=self.config.get("pass_phrase"),
            )

    async def stream_session(self):
        try:
            params = RealtimeParameters()
        except NameError:
            raise RuntimeError("OCI STT Realtime SDK is not available.")
        params.language_code = "en-US"
        params.model_domain = RealtimeParameters.MODEL_DOMAIN_GENERIC
        params.encoding = "audio/raw;rate=16000"
        params.partial_silence_threshold_in_ms = 0
        params.final_silence_threshold_in_ms = 2000
        params.punctuation = RealtimeParameters.PUNCTUATION_AUTO
        params.stabilize_partial_results = (
            RealtimeParameters.STABILIZE_PARTIAL_RESULTS_MEDIUM
        )
        result_queue = asyncio.Queue(maxsize=100)
        listener = _STTListener(result_queue)
        url = f"wss://realtime.aiservice.{self.region}.oci.oraclecloud.com"
        client = RealtimeSpeechClient(
            config=self.config,
            realtime_speech_parameters=params,
            listener=listener,
            service_endpoint=url,
            signer=self._authenticator(),
            compartment_id=self.compartment_id,
        )
        loop_task = asyncio.create_task(client.connect())
        conn_task = asyncio.create_task(listener.connected.wait())
        done_task = asyncio.create_task(listener.done.wait())
        try:
            _done, pending = await asyncio.wait(
                [conn_task, done_task],
                timeout=10.0,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()
        except Exception:
            pass

        if loop_task.done() and loop_task.exception():
            raise loop_task.exception()

        if not listener.connected.is_set():
            raise RuntimeError("Failed to connect STT listener.")

        return client, result_queue, listener.done, loop_task
