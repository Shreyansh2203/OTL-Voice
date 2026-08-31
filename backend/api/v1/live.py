from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from ...core import auth
from ...core.limiter import ws_tracker
from ...services import chat, fusion_catalogue, otl_client
from ...services.gemini_live import GeminiLiveSession

logger = logging.getLogger(__name__)

router = APIRouter(tags=["live_voice"])


@router.websocket("/api/voice/live")
async def live_voice_stream(websocket: WebSocket):
    """Bidirectional WebSocket endpoint for direct Audio-in to Audio-out Gemini Live session."""
    client_ip = websocket.client.host if websocket.client else "unknown"

    otl_session = (
        websocket.cookies.get(auth._session_cookie_name())
        or websocket.cookies.get("otl_session")
        or websocket.cookies.get("__Host-otl_session")
    )
    ctx = await auth.resolve(otl_session)
    if not ctx:
        logger.warning("Live Voice rejected: Unauthorized")
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION, reason="Unauthorized"
        )
        return

    if not await ws_tracker.acquire(client_ip):
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION, reason="Too many connections"
        )
        return

    await websocket.accept()

    session: GeminiLiveSession | None = None
    try:
        assignments = await fusion_catalogue.alist_assignments_for_worker(
            ctx.employee_id, ctx.full_name
        )
        system_prompt = chat.build_system_prompt(
            username=ctx.username,
            employee_id=ctx.employee_id,
            employee_name=ctx.full_name,
            assignments=assignments,
            recent_history="Direct voice dialogue session active.",
        )

        async def execute_tool(name: str, args: dict[str, Any]) -> Any:
            if name == "submit_timecard":
                entries = args.get("entries", [])
                for e in entries:
                    e.setdefault("employeeNumber", ctx.employee_id)
                    e.setdefault("employeeName", ctx.full_name)
                # Submit to OTL
                cred = otl_client.service_credential()
                res = await otl_client.acreate_many(cred, entries)
                return res
            elif name == "get_assigned_projects":
                return assignments
            raise ValueError(f"Unknown tool: {name}")

        session = GeminiLiveSession(
            system_prompt=system_prompt,
            tool_executor=execute_tool,
        )
        await session.connect()

        async def rx_mic_from_client():
            """Receive 16kHz PCM audio buffers from client and pipe to Gemini Live."""
            try:
                while True:
                    data = await websocket.receive_bytes()
                    if not data:
                        break
                    await session.send_audio_chunk(data)
            except WebSocketDisconnect:
                pass
            except Exception:
                logger.exception("Error receiving client audio in live voice session")

        async def tx_audio_to_client():
            """Receive synthetic audio/events from Gemini Live and stream to client."""
            try:
                async for event in session.receive_events():
                    ev_type = event.get("type")
                    if ev_type == "audio":
                        audio_data = event.get("data")
                        if audio_data:
                            await websocket.send_bytes(audio_data)
                    elif ev_type == "interrupted":
                        await websocket.send_json({"type": "barge_in"})
                    elif ev_type == "tool_executed":
                        await websocket.send_json(
                            {"type": "tool_executed", "calls": event.get("calls")}
                        )
            except WebSocketDisconnect:
                pass
            except Exception:
                logger.exception("Error transmitting live audio to client")

        rx_task = asyncio.create_task(rx_mic_from_client())
        tx_task = asyncio.create_task(tx_audio_to_client())

        await asyncio.gather(rx_task, tx_task, return_exceptions=True)

    except Exception as exc:
        logger.exception("Gemini Live Voice Session failed")
        try:
            await websocket.send_json({"error": f"Live session error: {exc}"})
        except Exception:
            pass
    finally:
        await ws_tracker.release(client_ip)
        if session:
            await session.close()
        try:
            await websocket.close()
        except Exception:
            pass
