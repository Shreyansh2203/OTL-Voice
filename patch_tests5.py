utf-8with open('backend/tests/conftest.py', 'r', encoding='utf-8') as f:
    content = f.read()
content = content.replace('mock.get_worker.return_value = {', 'mock.aget_worker = AsyncMock(return_value={"personNumber": "testuser", "fullName": "Test User"})\n        mock.get_worker.return_value = {')
with open('backend/tests/conftest.py', 'w', encoding='utf-8') as f:
    f.write(content)
with open('backend/tests/test_api.py', 'r', encoding='utf-8') as f:
    content2 = f.read()
content2 = content2.replace('mock_otl_client.get_worker', 'mock_otl_client.aget_worker')
with open('backend/tests/test_api.py', 'w', encoding='utf-8') as f:
    f.write(content2)