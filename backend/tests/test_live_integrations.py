import os

import pytest

from backend.services import otl_client
from backend.services.oci_genai import GenAIChatClient
from backend.services.oci_speech import SpeechClient

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_INTEGRATIONS", "false").strip().lower() != "true",
    reason="Set RUN_LIVE_INTEGRATIONS=true to run live integration tests",
)


@pytest.mark.asyncio
async def test_oracle_worker_lookup_live():
    person_number = os.getenv("LIVE_PERSON_NUMBER")
    assert person_number, "LIVE_PERSON_NUMBER is required"
    credential = otl_client.service_credential()
    worker = await otl_client.aget_worker(credential, person_number)
    assert worker["isActive"] is True


def test_oci_chat_live():
    client = GenAIChatClient()
    response = client.complete("", [{"role": "user", "content": "Reply with OK only."}])
    assert response.strip()


def test_oci_tts_live():
    audio = SpeechClient().synthesize("Integration test", rate=1.0)
    assert audio


@pytest.mark.asyncio
async def test_redis_live():
    url = os.getenv("REDIS_URL")
    if not url:
        pytest.skip("REDIS_URL is not configured")
    from redis.asyncio import from_url

    client = from_url(url)
    try:
        assert await client.ping()
    finally:
        await client.aclose()
