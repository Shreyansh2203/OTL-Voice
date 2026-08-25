utf-8with open('backend/core/auth.py', 'r', encoding='utf-8') as f:
    content = f.read()
old_init = '''                    cls._instance._use_redis = False
                    cls._instance._local_revoked: dict[str, float] = {}
                    cls._instance._local_lock = asyncio.Lock()'''
new_init = '''                    cls._instance._use_redis = False
                    cls._instance._local_revoked = {}
                    cls._instance._local_lock = asyncio.Lock()'''
content = content.replace(old_init, new_init)
old_class = '''class _TokenBlocklist:
    \"\"\"
    A singleton that tracks revoked JWTs.
    \"\"\"
    _instance: ClassVar[Self | None] = None
    _init_lock: ClassVar[Lock] = Lock()'''
new_class = '''class _TokenBlocklist:
    \"\"\"
    A singleton that tracks revoked JWTs.
    \"\"\"
    _instance: ClassVar[Self | None] = None
    _init_lock: ClassVar[Lock] = Lock()
    _local_revoked: dict[str, float]
    _local_lock: asyncio.Lock'''
content = content.replace(old_class, new_class)
with open('backend/core/auth.py', 'w', encoding='utf-8') as f:
    f.write(content)