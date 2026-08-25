utf-8with open('backend/core/auth.py', 'r', encoding='utf-8') as f:
    content = f.read()
content = content.replace('exp = int(payload.get("exp", time.time() + _ttl_seconds()))', 'exp = float(payload.get("exp", time.time() + _ttl_seconds()))')
content = content.replace('exp = int(time.time() + _ttl_seconds())', 'exp = float(time.time() + _ttl_seconds())')
with open('backend/core/auth.py', 'w', encoding='utf-8') as f:
    f.write(content)