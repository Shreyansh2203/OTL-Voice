with open('backend/services/otl_client.py', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace('time_records_url()', 'base_url()')
content = content.replace('map_otl_to_entry(resp.json())', 'resp.json()')

# also remove typing.Self import in auth.py
with open('backend/core/auth.py', 'r', encoding='utf-8') as f:
    auth_content = f.read()
auth_content = auth_content.replace('from typing import ClassVar, Self', 'from typing import ClassVar')
auth_content = auth_content.replace('def __new__(cls) -> ''_TokenBlocklist'':', 'def __new__(cls) -> ''_TokenBlocklist'':')
with open('backend/core/auth.py', 'w', encoding='utf-8') as f:
    f.write(auth_content)

# and asyncio in otl_client.py
content = content.replace('import asyncio\n', '')

with open('backend/services/otl_client.py', 'w', encoding='utf-8') as f:
    f.write(content)
