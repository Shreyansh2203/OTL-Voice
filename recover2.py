utf-8import httpx
with open('backend/services/otl_client.py', 'r', encoding='utf-8') as f:
    content = f.read()
content = content[:content.find('# --- Async Equivalents Recovered ---')]
async_additions = '''
import asyncio
def _async_client(cred: OtlCredential) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        auth=cred.auth,
        timeout=_timeout(),
        headers={"Accept": "application/json", "Accept-Encoding": "gzip"},
    )
async def avalidate(cred: OtlCredential) -> dict[str, Any]:
    async with _async_client(cred) as client:
        resp = await client.get(base_url(), params={"limit": 1})
    if resp.status_code in (401, 403):
        raise OtlError(
            resp.status_code,
            "OTL rejected the service account credential. Check "
            "OTL_SERVICE_USERNAME / OTL_SERVICE_PASSWORD.",
        )
    _raise_for_status(resp)
    return {"ok": True, "username": cred.username}
async def aget_worker(cred: OtlCredential, person_number: str) -> dict[str, Any] | None:
    return get_worker(cred, person_number)
async def alist_timecard_entries(
    cred: OtlCredential, limit: int = 10, offset: int = 0, person_number: str | None = None
) -> dict[str, Any]:
    return list_timecard_entries(cred, limit, offset, person_number)
async def acreate_many(
    cred: OtlCredential, entries: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    return create_many(cred, entries)
async def alist_worker_assignments(
    cred: OtlCredential, person_number: str, full_name: str = ""
) -> list[dict[str, Any]]:
    return list_worker_assignments(cred, person_number, full_name)
'''
with open('backend/services/otl_client.py', 'w', encoding='utf-8') as f:
    f.write(content + async_additions)