from unittest.mock import AsyncMock, patch

import pytest

from backend.services.gemini_live import GeminiLiveSession


@pytest.mark.asyncio
async def test_gemini_live_session_missing_key():
    with patch.dict("os.environ", {}, clear=True):
        session = GeminiLiveSession(system_prompt="Test prompt", api_key="")
        with pytest.raises(ValueError, match="is not configured"):
            await session.connect()


@pytest.mark.asyncio
async def test_gemini_live_session_send_audio():
    session = GeminiLiveSession(system_prompt="Test prompt", api_key="dummy_key")
    session.ws = AsyncMock()
    await session.send_audio_chunk(b"\x00\x01\x02\x03")
    assert session.ws.send.called


@pytest.mark.asyncio
async def test_gemini_live_session_events():
    session = GeminiLiveSession(system_prompt="Test prompt", api_key="dummy_key")
    mock_ws = AsyncMock()

    msg1 = '{"serverContent": {"interrupted": true, "modelTurn": {"parts": [{"inlineData": {"mimeType": "audio/pcm;rate=24000", "data": "AAAA"}}, {"text": "hello"}]}}}'
    msg2 = '{"toolCall": {"functionCalls": [{"id": "call_1", "name": "get_assigned_projects", "args": {}}]}}'

    async def msg_iter():
        yield msg1
        yield msg2

    mock_ws.__aiter__.side_effect = msg_iter
    session.ws = mock_ws

    executor = AsyncMock(return_value={"status": "ok"})
    session.tool_executor = executor

    events = []
    async for ev in session.receive_events():
        events.append(ev)

    assert any(e.get("type") == "interrupted" for e in events)
    assert any(e.get("type") == "audio" for e in events)
    assert any(e.get("type") == "text" for e in events)
    assert any(e.get("type") == "tool_executed" for e in events)
    assert executor.called

    await session.close()
    assert session._closed
