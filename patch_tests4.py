utf-8with open('backend/tests/test_auth.py', 'r', encoding='utf-8') as f:
    content = f.read()
content = content.replace('async async def', 'async def')
with open('backend/tests/test_auth.py', 'w', encoding='utf-8') as f:
    f.write(content)