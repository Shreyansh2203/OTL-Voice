utf-8with open('backend/services/otl_client.py', 'r', encoding='utf-8') as f:
    content = f.read()
content = content.replace(
    'return int(f) if f.is_integer() else f',
    'return round(f)'
)
content = content.replace(
    'return (resp.text or "")[:2000]',
    'return (resp.text or "")[:10000]'
)
async_add = '''
async def acreate_timecard_entry(cred: OtlCredential, entry: dict[str, Any]) -> dict[str, Any]:
    async with _async_client(cred) as client:
        resp = await client.post(time_records_url(), json=map_entry_to_otl(entry))
    _raise_for_status(resp)
    return map_otl_to_entry(resp.json())
'''
with open('backend/services/otl_client.py', 'w', encoding='utf-8') as f:
    f.write(content + async_add)