utf-8with open('backend/services/otl_client.py', 'r', encoding='utf-8') as f:
    content = f.read()
content = content.replace(
    "results.append({'ok': True, 'data': res})",
    "results.append({'ok': True, 'id': res.get('timeRecordEventRequestId')})"
)
with open('backend/services/otl_client.py', 'w', encoding='utf-8') as f:
    f.write(content)