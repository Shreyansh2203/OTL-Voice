utf-8with open('backend/tests/test_api.py', 'r', encoding='utf-8') as f:
    content = f.read()
content = content.replace('patch("backend.main.otl_client.get_worker"', 'patch("backend.main.otl_client.aget_worker"')
with open('backend/tests/test_api.py', 'w', encoding='utf-8') as f:
    f.write(content)