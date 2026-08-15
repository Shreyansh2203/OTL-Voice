
from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator

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

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv is optional at runtime
    pass


# --------------------------------------------------------------------------- #
# Configuration helpers
# --------------------------------------------------------------------------- #
def _env(name: str, default: str = "") -> str:
    value = os.getenv(name)
    return value.strip() if value else default


def _normalize_pem(raw: str) -> str:
    text = raw.strip()
    if "\\n" in text:
        text = text.replace("\\n", "\n")

    match = re.search(
        r"-----BEGIN ([A-Z0-9 ]+?)-----(.*?)-----END \1-----",
        text,
        re.DOTALL,
    )
    if not match:
        # Could not recognise the structure; return as-is and let the signer
        # raise a clear error.
        return text

    label = match.group(1).strip()
    body = re.sub(r"\s+", "", match.group(2))  # strip all whitespace/newlines
    wrapped = "\n".join(body[i : i + 64] for i in range(0, len(body), 64))
    return f"-----BEGIN {label}-----\n{wrapped}\n-----END {label}-----\n"


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

    # Fallback: use ~/.oci/config profile (local development).
    profile = _env("OCI_CONFIG_PROFILE", "DEFAULT")
    return oci.config.from_file(profile_name=profile)


def _service_endpoint(region: str) -> str:
    explicit = _env("OCI_SERVICE_ENDPOINT")
    if explicit:
        return explicit
    return f"https://inference.generativeai.{region}.oci.oraclecloud.com"


# --------------------------------------------------------------------------- #
# Chat client
# --------------------------------------------------------------------------- #
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

    # -- request building ---------------------------------------------------- #
    def _to_messages(self, system_prompt: str, history: list[dict]) -> list[Message]:
        messages: list[Message] = []
        if system_prompt:
            messages.append(
                Message(role="SYSTEM", content=[TextContent(text=system_prompt)])
            )
        for turn in history:
            role = "USER" if turn.get("role") == "user" else "ASSISTANT"
            content = turn.get("content", "")
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

    # -- non-streaming ------------------------------------------------------- #
    def complete(self, system_prompt: str, history: list[dict]) -> str:
        messages = self._to_messages(system_prompt, history)
        response = self.client.chat(self._chat_detail(messages, stream=False))
        return self._extract_full_text(response.data)

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

        # Fallback: walk the serialized dict form for any "text" fields.
        try:
            blob = json.loads(str(data))
            found: list[str] = []

            def _walk(node):
                if isinstance(node, dict):
                    if isinstance(node.get("text"), str):
                        found.append(node["text"])
                    for value in node.values():
                        _walk(value)
                elif isinstance(node, list):
                    for item in node:
                        _walk(item)

            _walk(blob)
            if found:
                return "".join(found)
        except Exception:
            pass
        return ""

    # -- streaming ----------------------------------------------------------- #
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
        except Exception:
            if not produced_any:
                # Surface the non-streaming result (or its own error) to the UI.
                yield self.complete(system_prompt, history)
                return
            # Streaming already produced partial text; stop gracefully.
            return

        if not produced_any:
            yield self.complete(system_prompt, history)

    @staticmethod
    def _extract_delta(raw: str) -> str:
        try:
            obj = json.loads(raw)
        except Exception:
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

    # -- diagnostics --------------------------------------------------------- #
    def ping(self) -> str:
        return self.complete(
            "You are a health check. Reply with the single word: OK.",
            [{"role": "user", "content": "ping"}],
        )
