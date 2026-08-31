from __future__ import annotations

import asyncio
import logging
import os
from functools import lru_cache

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import StreamingResponse

from ...core import auth
from ...core.auth import SessionContext
from ...core.limiter import ws_tracker
from ...schemas.chat import ChatBody, TtsBody
from ...services import chat, fusion_catalogue, otl_client

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat", "speech"])


def _cors_origins() -> list[str]:
    raw = os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://localhost:4173,http://localhost:8000,http://localhost,http://127.0.0.1:5173,http://127.0.0.1:4173,http://127.0.0.1:8000",
    )
    return [o.strip() for o in raw.split(",") if o.strip()]


@lru_cache(maxsize=1)
def _speech_client():
    from ...services.oci_speech import SpeechClient

    return SpeechClient()


@router.post("/api/chat")
async def chat_stream(
    body: ChatBody, ctx: SessionContext = Depends(auth.current_session)
) -> StreamingResponse:
    assignments = await fusion_catalogue.alist_assignments_for_worker(ctx.employee_id, ctx.full_name)
    recent_history_str = ""
    try:
        recent = await otl_client.alist_timecard_entries(
            otl_client.service_credential(), limit=1, offset=0, person_number=ctx.employee_id
        )
        items = recent.get("items", [])
        if items:
            latest = items[0]
            attrs = latest.get("timeRecordEventAttribute") or latest.get("timeAttributes", [])
            proj = next((a.get("attributeValue") for a in attrs if a.get("attributeName") == "PJC_PROJECT_ID"), None)
            hours = latest.get("measure", "")
            if proj:
                p_info = fusion_catalogue.get_project_by_id(proj)
                if p_info:
                    recent_history_str = f"User recently logged {hours} hours on {p_info.get('project_name')} (Project {p_info.get('project_number')})."
    except Exception:
        pass
    system_prompt = chat.build_system_prompt(
        username=ctx.username,
        employee_id=ctx.employee_id,
        employee_name=ctx.full_name,
        assignments=assignments,
        recent_history=recent_history_str,
    )
    history = [
        {"role": m.role, "content": m.content}
        for m in body.messages
        if m.content and m.content.strip()
    ]
    return StreamingResponse(
        chat.stream_sse(system_prompt, history),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/api/tts")
def tts(
    body: TtsBody, _: SessionContext = Depends(auth.current_session)
) -> Response:
    try:
        client = _speech_client()
        audio = client.synthesize(body.text, rate=body.rate)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Speech synthesis unavailable: {exc}",
        )
    return Response(content=audio, media_type=client.mime)


@router.websocket("/api/stt/stream")
async def stt_stream(websocket: WebSocket):
    client_ip = websocket.client.host if websocket.client else "unknown"
    origin = websocket.headers.get("origin") or websocket.headers.get("sec-websocket-origin")
    allowed_origins = _cors_origins()
    if origin and allowed_origins and origin not in allowed_origins:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Origin not allowed")
        return
    otl_session = (
        websocket.cookies.get(auth._session_cookie_name())
        or websocket.cookies.get("otl_session")
        or websocket.cookies.get("__Host-otl_session")
    )
    ctx = await auth.resolve(otl_session)
    if not ctx:
        logger.warning("STT WebSocket rejected: Unauthorized (no valid session cookie found)")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Unauthorized")
        return
    if not await ws_tracker.acquire(client_ip):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Too many connections")
        return
    await websocket.accept()
    oci_client = None
    try:
        from ...services.oci_speech import STTClient

        client = STTClient()
        oci_client, result_queue, done_event, loop_task = await client.stream_session()
        send_semaphore = asyncio.Semaphore(10)
        backpressure_active = False

        async def receive_from_frontend():
            nonlocal backpressure_active
            try:
                while True:
                    data = await websocket.receive_bytes()
                    if not data:
                        await oci_client.request_final_result()
                        break
                    if len(data) > 64 * 1024:
                        logging.getLogger(__name__).warning("STT message too large: %d bytes", len(data))
                        continue
                    if result_queue.qsize() > 50:
                        backpressure_active = True
                        await asyncio.sleep(0.01)
                    else:
                        backpressure_active = False
                    await oci_client.send_data(data)
            except WebSocketDisconnect:
                pass
            except Exception:
                logger.exception("STT RX Error")

        async def send_to_frontend():
            try:
                while not done_event.is_set() or not result_queue.empty():
                    fetch_task = asyncio.create_task(result_queue.get())
                    done_task = asyncio.create_task(done_event.wait())
                    done, pending = await asyncio.wait(
                        [fetch_task, done_task],
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if fetch_task in done:
                        result = fetch_task.result()
                        async with send_semaphore:
                            await websocket.send_json(result)
                    for t in pending:
                        t.cancel()
            except WebSocketDisconnect:
                pass
            except Exception:
                logging.getLogger(__name__).exception("STT TX Error")

        rx_task = asyncio.create_task(receive_from_frontend())
        tx_task = asyncio.create_task(send_to_frontend())
        results = await asyncio.gather(rx_task, tx_task, loop_task, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                logging.getLogger(__name__).exception("STT task error", exc_info=result)
    except Exception:
        logging.getLogger(__name__).exception("STT Session Error")
    finally:
        await ws_tracker.release(client_ip)
        try:
            if oci_client:
                oci_client.close()
        except Exception:
            pass
        try:
            await websocket.close()
        except Exception:
            pass




