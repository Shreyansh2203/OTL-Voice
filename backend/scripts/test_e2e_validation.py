"""End-to-end validation of the catalogue-backed flow."""

import httpx

BASE = "http://localhost"

# Test employees: one WITH projects, one WITHOUT
test_cases = [
    ("10464", "Mahesh Babu S"),   # Has 2 projects
    ("90407", "prathmesh nayadkar"),  # Has 0 projects (but has timecards)
]

for emp_no, expected_name in test_cases:
    print(f"\n{'='*60}")
    print(f"TESTING Employee #{emp_no} ({expected_name})")
    print(f"{'='*60}")

    # 1. Login
    r = httpx.post(f"{BASE}/api/auth/login", json={"username": emp_no, "password": ""}, timeout=15)
    print(f"\n[1] LOGIN: Status {r.status_code}")
    if r.status_code != 200:
        print(f"    FAILED: {r.text}")
        continue
    login_data = r.json()
    print(f"    Name: {login_data['fullName']}")
    cookie = r.cookies.get("otl_session")
    if not cookie:
        print("    FAILED: No cookie returned.")
        continue
    print(f"    Session: {cookie[:20]}...")

    client = httpx.Client(cookies={"otl_session": cookie}, timeout=15)

    # 2. Assignments
    r = client.get(f"{BASE}/api/labour/assignments")
    print(f"\n[2] ASSIGNMENTS: Status {r.status_code}")
    assignments = r.json()
    work_orders = assignments.get("workOrders", [])
    print(f"    Work Orders: {len(work_orders)}")
    for wo in work_orders[:3]:
        for p in wo.get("projects", []):
            tasks = [t["taskDetails"] for t in p.get("tasks", [])[:3]]
            print(f"    -> Project #{p['projectNo']}: {p['projectName']}")
            print(f"       Tasks: {', '.join(tasks) if tasks else 'None'}")

    # 3. Session check
    r = client.get(f"{BASE}/api/auth/session")
    print(f"\n[3] SESSION: Status {r.status_code}")
    print(f"    Identity: {r.json()}")

    # 4. Timecards
    r = client.get(f"{BASE}/api/otl/timecards?limit=3")
    print(f"\n[4] TIMECARDS: Status {r.status_code}")
    tc_data = r.json()
    items = tc_data.get("items", [])
    print(f"    Found {len(items)} timecard records")

    # 5. Logout
    r = client.post(f"{BASE}/api/auth/logout")
    print(f"\n[5] LOGOUT: Status {r.status_code}")

print(f"\n{'='*60}")
print("ALL TESTS COMPLETE")
print(f"{'='*60}")
