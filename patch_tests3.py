utf-8import httpx
with open('backend/services/otl_client.py', 'r', encoding='utf-8') as f:
    content = f.read()
old_acreate = '''async def acreate_many(
    cred: OtlCredential, entries: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    return create_many(cred, entries)'''
new_acreate = '''async def acreate_many(
    cred: OtlCredential, entries: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    results = []
    for entry in entries:
        try:
            res = await acreate_timecard_entry(cred, entry)
            results.append({'ok': True, 'data': res})
        except Exception as e:
            results.append({'ok': False, 'error': str(e), 'entry': entry})
    return results'''
content = content.replace(old_acreate, new_acreate)
with open('backend/services/otl_client.py', 'w', encoding='utf-8') as f:
    f.write(content)
with open('backend/tests/test_api.py', 'r', encoding='utf-8') as f:
    test_api = f.read()
test_api = test_api.replace('otl_client.get_worker', 'otl_client.aget_worker')
test_api = test_api.replace('otl_client.list_timecard_entries', 'otl_client.alist_timecard_entries')
test_api = test_api.replace('otl_client.create_many', 'otl_client.acreate_many')
test_api = test_api.replace('fusion_catalogue.list_assignments_for_worker', 'fusion_catalogue.alist_assignments_for_worker')
with open('backend/tests/test_api.py', 'w', encoding='utf-8') as f:
    f.write(test_api)
with open('backend/tests/test_auth.py', 'r', encoding='utf-8') as f:
    test_auth = f.read()
test_auth = test_auth.replace('destroy(token)', 'await destroy(token)')
test_auth = test_auth.replace('destroy(None)', 'await destroy(None)')
test_auth = test_auth.replace('def test_destroy(', 'async def test_destroy(')
with open('backend/tests/test_auth.py', 'w', encoding='utf-8') as f:
    f.write(test_auth)