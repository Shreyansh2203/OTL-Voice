from __future__ import annotations

import base64
import inspect
import json
import logging
import os
from collections.abc import Callable
from typing import Any

import websockets
from websockets.asyncio.client import ClientConnection

logger = logging.getLogger(__name__)

GEMINI_LIVE_WS_URL = "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1alpha.GenerativeService.BidiGenerateContent"

OTL_TOOLS = [
    {
        "functionDeclarations": [
            {
                "name": "submit_timecard",
                "description": "Submit confirmed timecard entries to Oracle Time & Labor (OTL).",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "entries": {
                            "type": "ARRAY",
                            "description": "List of timecard entries to log.",
                            "items": {
                                "type": "OBJECT",
                                "properties": {
                                    "projectNo": {
                                        "type": "INTEGER",
                                        "description": "Project number from assigned work.",
                                    },
                                    "projectName": {
                                        "type": "STRING",
                                        "description": "Project name.",
                                    },
                                    "workOrder": {
                                        "type": "STRING",
                                        "description": "Associated work order.",
                                    },
                                    "taskDetails": {
                                        "type": "STRING",
                                        "description": "Short description of tasks performed.",
                                    },
                                    "hours": {
                                        "type": "NUMBER",
                                        "description": "Hours spent on this task.",
                                    },
                                    "date": {
                                        "type": "STRING",
                                        "description": "Date in YYYY-MM-DD format.",
                                    },
                                },
                                "required": [
                                    "projectNo",
                                    "projectName",
                                    "workOrder",
                                    "taskDetails",
                                    "hours",
                                    "date",
                                ],
                            },
                        }
                    },
                    "required": ["entries"],
                },
            },
            {
                "name": "get_assigned_projects",
                "description": "Retrieve the current list of assigned projects, work orders, and tasks for the worker.",
                "parameters": {"type": "OBJECT", "properties": {}},
            },
        ]
    }
]


class GeminiLiveSession:
    """Manages a bidirectional live multimodal audio session with Gemini."""

    def __init__(
        self,
        system_prompt: str,
        voice_name: str = "Aoede",
        api_key: str | None = None,
        tool_executor: Callable[[str, dict[str, Any]], Any] | None = None,
    ) -> None:
        self.api_key = (
            api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        )
        self.system_prompt = system_prompt
        self.voice_name = voice_name
        self.tool_executor = tool_executor
        self.ws: ClientConnection | None = None
        self._closed = False

    async def connect(self) -> None:
        if not self.api_key:
            raise ValueError(
                "GEMINI_API_KEY or GOOGLE_API_KEY is not configured for Gemini Live session."
            )
        url = f"{GEMINI_LIVE_WS_URL}?key={self.api_key}"
        ping_interval = int(os.getenv("GEMINI_LIVE_PING_INTERVAL", "30"))
        ping_timeout = int(os.getenv("GEMINI_LIVE_PING_TIMEOUT", "10"))
        self.ws = await websockets.connect(
            url, ping_interval=ping_interval, ping_timeout=ping_timeout
        )

        # Send initial Setup message
        setup_payload = {
            "setup": {
                "model": "models/gemini-2.0-flash-exp",
                "generationConfig": {
                    "responseModalities": ["AUDIO"],
                    "speechConfig": {
                        "voiceConfig": {
                            "prebuiltVoiceConfig": {"voiceName": self.voice_name}
                        }
                    },
                },
                "systemInstruction": {"parts": [{"text": self.system_prompt}]},
                "tools": OTL_TOOLS,
            }
        }
        await self.ws.send(json.dumps(setup_payload))
        # Receive setup confirmation
        resp = await self.ws.recv()
        logger.info(
            "Gemini Live session initialized: %s",
            resp[:100] if isinstance(resp, str) else "binary",
        )

    async def send_audio_chunk(self, pcm_bytes: bytes) -> None:
        """Stream 16kHz linear PCM audio chunk to Gemini."""
        if not self.ws or self._closed:
            return
        b64_audio = base64.b64encode(pcm_bytes).decode("ascii")
        msg = {
            "realtimeInput": {
                "mediaChunks": [
                    {
                        "mimeType": "audio/pcm;rate=16000",
                        "data": b64_audio,
                    }
                ]
            }
        }
        await self.ws.send(json.dumps(msg))

    async def receive_events(self):
        """Async generator yielding audio responses, transcripts, or tool calls from Gemini."""
        if not self.ws:
            return

        try:
            async for raw_msg in self.ws:
                if self._closed:
                    break
                data = json.loads(raw_msg)
                server_content = data.get("serverContent")
                if server_content:
                    # Check for server-side interruption / barge-in
                    if server_content.get("interrupted"):
                        yield {"type": "interrupted"}

                    model_turn = server_content.get("modelTurn")
                    if model_turn:
                        parts = model_turn.get("parts", [])
                        for part in parts:
                            inline_data = part.get("inlineData")
                            if inline_data and inline_data.get(
                                "mimeType", ""
                            ).startswith("audio/"):
                                audio_bytes = base64.b64decode(
                                    inline_data.get("data", "")
                                )
                                yield {"type": "audio", "data": audio_bytes}
                            if part.get("text"):
                                yield {"type": "text", "data": part.get("text")}

                # Handle Tool Calls
                tool_call = data.get("toolCall")
                if tool_call and self.tool_executor:
                    calls = tool_call.get("functionCalls", [])
                    responses = []
                    for call in calls:
                        name = call.get("name")
                        args = call.get("args", {})
                        call_id = call.get("id")
                        try:
                            res = self.tool_executor(name, args)
                            result = (
                                await res if inspect.isawaitable(res) else res
                            )
                            responses.append(
                                {
                                    "id": call_id,
                                    "name": name,
                                    "response": {"result": result},
                                }
                            )
                        except Exception as err:
                            responses.append(
                                {
                                    "id": call_id,
                                    "name": name,
                                    "response": {"error": str(err)},
                                }
                            )

                    # Send tool response back to session
                    tool_resp_msg = {"toolResponse": {"functionResponses": responses}}
                    await self.ws.send(json.dumps(tool_resp_msg))
                    yield {"type": "tool_executed", "calls": responses}
        except websockets.ConnectionClosed:
            pass
        except Exception:
            logger.exception("Error in Gemini Live session event stream")

    async def close(self) -> None:
        self._closed = True
        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass
            self.ws = None
