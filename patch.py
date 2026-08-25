utf-8import sys
def patch_main():
    with open('backend/main.py', 'r', encoding='utf-8') as f:
        content = f.read()
    content = content.replace(
        'worker_data = otl_client.get_worker(user_cred, person_number)',
        'worker_data = await otl_client.aget_worker(user_cred, person_number)'
    )
    old_refresh = '''@app.post("/api/auth/refresh")
def refresh_session(
    response: Response,
    ctx: SessionContext = Depends(auth.current_session),
) -> dict[str, str]:
    \"\"\"
    Refreshes the current session by issuing a new JWT and resetting the cookie TTL.
    \"\"\"'''
    new_refresh = '''@app.post("/api/auth/refresh")
async def refresh_session(
    request: Request,
    response: Response,
    ctx: SessionContext = Depends(auth.current_session),
) -> dict[str, str]:
    \"\"\"
    Refreshes the current session by issuing a new JWT and resetting the cookie TTL.
    \"\"\"
    old_token = request.cookies.get(auth._session_cookie_name())
    if old_token:
        await auth.destroy(old_token)'''
    content = content.replace(old_refresh, new_refresh)
    old_ws = '''    # Limit max message size to 64KB to prevent DoS
    websocket._max_message_size = 64 * 1024
    await websocket.accept()'''
    new_ws = '''    # WebSocket message size limits should be configured at the server level.
    await websocket.accept()'''
    content = content.replace(old_ws, new_ws)
    old_redis = '''        if self._redis is None:
            try:
                self._redis = redis.from_url(self.redis_url, decode_responses=True)'''
    new_redis = '''        if self._redis is None:
            if not self.redis_url:
                self._use_redis = False
                return None
            try:
                self._redis = redis.from_url(self.redis_url, decode_responses=True)'''
    content = content.replace(old_redis, new_redis)
    old_protocol = '''class HasIdentity(Protocol):
    username: str
    employee_id: str
    full_name: str'''
    new_protocol = '''class HasIdentity(Protocol):
    @property
    def username(self) -> str: ...
    @property
    def employee_id(self) -> str: ...
    @property
    def full_name(self) -> str: ...'''
    content = content.replace(old_protocol, new_protocol)
    with open('backend/main.py', 'w', encoding='utf-8') as f:
        f.write(content)
patch_main()