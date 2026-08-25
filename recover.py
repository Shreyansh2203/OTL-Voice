utf-8import httpx
with open('backend/services/otl_client.py', 'r', encoding='utf-8') as f:
    content = f.read()
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
    async with _async_client(cred) as client:
        resp = await client.get(
            hcm_base_url() + f"/workers",
            params={"q": f"PersonNumber={person_number}", "limit": 1}
        )
    if resp.status_code == 404:
        return None
    _raise_for_status(resp)
    items = resp.json().get("items", [])
    if not items:
        return None
    worker = items[0]
    return {
        "personNumber": worker.get("PersonNumber"),
        "fullName": worker.get("DisplayName", worker.get("PersonName", worker.get("PersonNumber"))),
    }
async def alist_timecard_entries(
    cred: OtlCredential,
    limit: int = 10,
    offset: int = 0,
    person_number: str | None = None,
) -> list[dict[str, Any]]:
    params = {"limit": limit, "offset": offset, "orderBy": "startTime:desc"}
    if person_number:
        params["q"] = f"reporterId={person_number}"
    async with _async_client(cred) as client:
        resp = await client.get(time_records_url(), params=params)
    _raise_for_status(resp)
    items = resp.json().get("items", [])
    return [map_otl_to_entry(item) for item in items]
async def acreate_many(
    cred: OtlCredential, entries: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    results = []
    async with _async_client(cred) as client:
        for entry in entries:
            try:
                payload = map_entry_to_otl(entry)
                resp = await client.post(time_records_url(), json=payload)
                _raise_for_status(resp)
                results.append({"ok": True, "data": map_otl_to_entry(resp.json())})
            except Exception as e:
                results.append({"ok": False, "error": str(e), "entry": entry})
    return results
async def alist_assignments_for_worker(
    cred: OtlCredential, person_number: str, full_name: str = ""
) -> list[dict[str, Any]]:
    pass
'''
with open('backend/services/otl_client.py', 'a', encoding='utf-8') as f:
    f.write(async_additions)