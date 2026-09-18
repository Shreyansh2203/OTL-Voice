import os

os.environ['TEST_MODE'] = 'true'
os.environ['SESSION_COOKIE_SECURE'] = 'false'

import sys

from fastapi.testclient import TestClient

from backend.main import app


def run_test():
    print("--- STARTING END-TO-END TEST ---\n")
    client = TestClient(app)

    print("1. Authenticating as Person 10021 via POST /api/auth/login")
    res_login = client.post("/api/auth/login", json={"personNumber": "10021"})
    
    if res_login.status_code != 200:
        print(f"FAIL: Login returned {res_login.status_code} - {res_login.text}")
        sys.exit(1)
    
    print("SUCCESS: Logged in securely and received session cookies.\n")

    print("2. Testing AI Chat Connection via POST /api/chat")
    res_chat = client.post("/api/chat", json={"messages": [{"role": "user", "content": "Hello, are you there?"}]})
    
    if res_chat.status_code != 200:
        print(f"FAIL: Chat returned {res_chat.status_code} - {res_chat.text}")
        sys.exit(1)

    print("SUCCESS: Chat connected. Streaming output from Oracle Cloud:\n")
    print("===================================================")
    for chunk in res_chat.iter_bytes():
        if chunk:
            print(chunk.decode('utf-8'), end="", flush=True)
    print("\n===================================================")
    
    print("\n--- TEST COMPLETE ---")

if __name__ == "__main__":
    run_test()
