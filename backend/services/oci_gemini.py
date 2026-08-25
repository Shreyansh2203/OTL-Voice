
from __future__ import annotations

import json
import logging
import os
import random
import re
import time
from collections.abc import Callable, Iterator
from typing import TypeVar

import oci
from oci.generative_ai_inference import GenerativeAiInferenceClient
from oci.generative_ai_inference.models import (
    BaseChatRequest,
    ChatDetails,
    GenericChatRequest,
    Message,
    OnDemandServingMode,
    TextContent,
)

logger = logging.getLogger(__name__)
T = TypeVar("T")
def _retry_with_backoff[T](
    func: Callable[[], T],
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    retryable_exceptions: tuple[type[Exception], ...] = (
        oci.exceptions.ServiceError,
        ConnectionError,
        TimeoutError,
    ),
) -> T:
    last_exception: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return func()
        except retryable_exceptions as e:
            last_exception = e
            if attempt < max_retries:
                delay = min(base_delay * (2 ** attempt), max_delay)
                delay *= (0.5 + random.random() * 0.5)
                time.sleep(delay)
            else:
                break
    if last_exception is not None:
        raise last_exception
    raise RuntimeError("Retry loop failed without an exception")
def _env(name: str, default: str = "") -> str:
    value = os.getenv(name)
    return value.strip() if value else default
def _normalize_pem(raw: str) -> str:
    text = raw.strip()
    if "\\n" in text:
        text = text.replace("\\n", "\n")
    match = re.search(
        r"(-----BEGIN ([A-Z0-9 ]+?)-----\s*.*?\s*-----END \2-----)",
        text,
        re.DOTALL,
    )
    if not match:
        return text
    pem_block = match.group(1).strip()
    lines = pem_block.split("\n")
    if len(lines) < 3:
        return pem_block
    header = lines[0].strip()
    footer = lines[-1].strip()
    body_lines = [line.strip() for line in lines[1:-1] if line.strip()]
    body = "".join(body_lines)
    wrapped = "\n".join(body[i:i + 64] for i in range(0, len(body), 64))
    return f"{header}\n{wrapped}\n{footer}\n"
def build_oci_config() -> dict[str, str]:
    region = _env("OCI_REGION")
    user = _env("OCI_USER_OCID")
    tenancy = _env("OCI_TENANCY_OCID")
    fingerprint = _env("OCI_FINGERPRINT")
    if user and tenancy and fingerprint:
        config = {
            "user": user,
            "tenancy": tenancy,
            "fingerprint": fingerprint,
            "region": region,
        }
        inline_key = os.getenv("OCI_PRIVATE_KEY")
        key_path = _env("OCI_PRIVATE_KEY_PATH")
        if inline_key and inline_key.strip():
            config["key_content"] = _normalize_pem(inline_key)
        elif key_path:
            config["key_file"] = key_path
        else:
            raise RuntimeError(
                "No private key found. Set OCI_PRIVATE_KEY (inline PEM) or "
                "OCI_PRIVATE_KEY_PATH in your .env."
            )
        passphrase = os.getenv("OCI_PRIVATE_KEY_PASSPHRASE")
        if passphrase and passphrase.strip():
            config["pass_phrase"] = passphrase.strip()
        return config
    profile = _env("OCI_CONFIG_PROFILE", "DEFAULT")
    return oci.config.from_file(profile_name=profile)
def _service_endpoint(region: str) -> str:
    explicit = _env("OCI_SERVICE_ENDPOINT")
    if explicit:
        return explicit
    return f"https://inference.generativeai.{region}.oci.oraclecloud.com"
class GeminiChatClient:
    def __init__(self) -> None:
        self.config = build_oci_config()
        self.region = self.config.get("region") or _env("OCI_REGION")
        self.compartment_id = _env("OCI_COMPARTMENT_ID")
        if not self.compartment_id:
            raise RuntimeError("OCI_COMPARTMENT_ID is not set in your .env.")
        self.model_id = _env("CHAT_MODEL_ID", "google.gemini-2.5-flash")
        self.temperature = float(_env("CHAT_TEMPERATURE", "0.3"))
        self.top_p = float(_env("CHAT_TOP_P", "0.95"))
        self.max_tokens = int(_env("CHAT_MAX_TOKENS", "2048"))
        read_timeout = int(_env("REQUEST_TIMEOUT_SECONDS", "300"))
        self.client = GenerativeAiInferenceClient(
            config=self.config,
            service_endpoint=_service_endpoint(self.region),
            retry_strategy=oci.retry.NoneRetryStrategy(),
            timeout=(10, read_timeout),
        )
    def _to_messages(self, system_prompt: str, history: list[dict]) -> list[Message]:
        messages: list[Message] = []
        if system_prompt:
            messages.append(
                Message(role="SYSTEM", content=[TextContent(text=system_prompt)])
            )
        for turn in history:
            r = turn.get("role")
            if r == "user":
                role = "USER"
            elif r in ("assistant", "model"):
                role = "ASSISTANT"
            else:
                logger.warning("Dropping message with unexpected role: %s", r)
                continue
            
            content = turn.get("content", "")
            if messages and messages[-1].role == role:
                prev_text = getattr(messages[-1].content[0], "text", "")
                messages[-1].content[0] = TextContent(text=prev_text + "\n\n" + content)
            else:
                messages.append(Message(role=role, content=[TextContent(text=content)]))
        return messages
    def _chat_detail(self, messages: list[Message], stream: bool) -> ChatDetails:
        chat_request = GenericChatRequest(
            api_format=BaseChatRequest.API_FORMAT_GENERIC,
            messages=messages,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            top_p=self.top_p,
            is_stream=stream,
        )
        return ChatDetails(
            compartment_id=self.compartment_id,
            serving_mode=OnDemandServingMode(model_id=self.model_id),
            chat_request=chat_request,
        )
    def complete(self, system_prompt: str, history: list[dict]) -> str:
        messages = self._to_messages(system_prompt, history)
        detail = self._chat_detail(messages, stream=False)
        def _call():
            response = self.client.chat(detail)
            return self._extract_full_text(response.data)
        return _retry_with_backoff(_call, max_retries=3, base_delay=1.0)
    @staticmethod
    def _extract_full_text(data) -> str:
        try:
            choice = data.chat_response.choices[0]
            parts = choice.message.content or []
            text = "".join(getattr(p, "text", "") or "" for p in parts)
            if text:
                return text
        except Exception:
            pass
        try:
            blob = oci.util.to_dict(data) if hasattr(oci, "util") and hasattr(oci.util, "to_dict") else None
            if not blob and isinstance(data, dict):
                blob = data
            elif not blob:
                try:
                    blob = json.loads(str(data))
                except Exception:
                    blob = {}
            found: list[str] = []
            def _walk(node, depth=0):
                if depth > 100:
                    logger.warning("Max depth exceeded in _extract_full_text")
                    return
                if isinstance(node, dict):
                    if isinstance(node.get("text"), str):
                        found.append(node["text"])
                    for value in node.values():
                        _walk(value, depth + 1)
                elif isinstance(node, list):
                    for item in node:
                        _walk(item, depth + 1)
            _walk(blob)
            if found:
                return "".join(found)
        except Exception:
            pass
        return ""
    def stream(self, system_prompt: str, history: list[dict]) -> Iterator[str]:
        messages = self._to_messages(system_prompt, history)
        detail = self._chat_detail(messages, stream=True)
        produced_any = False
        try:
            response = self.client.chat(detail)
            for event in response.data.events():
                raw = getattr(event, "data", None)
                if not raw:
                    continue
                if raw.strip() in ("[DONE]", "DONE"):
                    break
                delta = self._extract_delta(raw)
                if delta:
                    produced_any = True
                    yield delta
        except Exception as exc:
            if not produced_any:
                logger.warning("Streaming failed before producing output, falling back to non-streaming: %s", exc)
                yield self.complete(system_prompt, history)
                return
            logger.error("Streaming failed after producing partial output: %s", exc)
            yield json.dumps({"error": str(exc)})
            return
        if not produced_any:
            yield self.complete(system_prompt, history)
    @staticmethod
    def _extract_delta(raw: str) -> str:
        try:
            obj = json.loads(raw)
        except Exception:
            return ""
        if not isinstance(obj, dict):
            return ""
        message = obj.get("message")
        if isinstance(message, dict):
            content = message.get("content") or []
            text = "".join(
                c.get("text", "")
                for c in content
                if isinstance(c, dict) and c.get("text")
            )
            if text:
                return text
        if isinstance(obj.get("text"), str):
            return obj["text"]
        return ""
    def ping(self) -> str:
        return self.complete(
            "You are a health check. Reply with the single word: OK.",
            [{"role": "user", "content": "ping"}],
        )