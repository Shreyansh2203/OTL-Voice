utf-8with open('backend/services/chat.py', 'r', encoding='utf-8') as f:
    content = f.read()
content = content.replace('def _safe_err(msg: str) -> str:', 'def _safe_err(msg: str | Exception) -> str:')
with open('backend/services/chat.py', 'w', encoding='utf-8') as f:
    f.write(content)