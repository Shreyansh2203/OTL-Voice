import json
import os
import urllib.parse

import httpx
from dotenv import load_dotenv

load_dotenv()

DEFAULT_USERNAME = os.getenv("OTL_SERVICE_USERNAME", "").strip()
DEFAULT_PASSWORD = os.getenv("OTL_SERVICE_PASSWORD", "")
DEFAULT_OTL_URL = os.getenv("OTL_BASE_URL", "")
if not DEFAULT_OTL_URL:
    print("Error: OTL_BASE_URL environment variable is not set. Please configure it in .env")
    exit(1)

parsed = urllib.parse.urlparse(DEFAULT_OTL_URL)
HOST_URL = f"{parsed.scheme}://{parsed.netloc}"

def get_client(username: str, password: str) -> httpx.Client:
    return httpx.Client(
        auth=(username, password),
        timeout=30.0,
        headers={"Accept": "application/json", "Accept-Encoding": "gzip"},
    )

def main():
    print("=" * 65)
    print(" Oracle Fusion Cloud - Interactive Data Explorer")
    print(f" Target Host: {HOST_URL}")
    print("=" * 65)

    use_default = input(f"Use configured credentials ({DEFAULT_USERNAME})? [Y/n]: ").strip().lower()
    if use_default in ("n", "no"):
        username = input("Enter Oracle Fusion Username: ").strip()
        import getpass
        password = getpass.getpass("Enter Oracle Fusion Password: ")
    else:
        username = DEFAULT_USERNAME
        password = DEFAULT_PASSWORD

    client = get_client(username, password)

    while True:
        print("\n" + "-" * 65)
        print("Choose an action:")
        print("  1. Search Worker/Employee (by Person Number or Name)")
        print("  2. List Latest Projects")
        print("  3. Get Tasks & Team Members for a Project")
        print("  4. View Recent Timecards")
        print("  5. Test Custom REST Endpoint Path")
        print("  0. Exit")
        print("-" * 65)
        
        choice = input("Enter choice (0-5): ").strip()
        
        if choice == "0":
            print("Goodbye!")
            break

        elif choice == "1":
            search_val = input("Enter Person Number (or press Enter to list first 10): ").strip()
            if search_val:
                url = f"{HOST_URL}/hcmRestApi/resources/11.13.18.05/workers"
                params = {
                    "q": f"PersonNumber='{search_val}'",
                    "expand": "names,emails"
                }
            else:
                url = f"{HOST_URL}/hcmRestApi/resources/11.13.18.05/workers"
                params = {"expand": "names", "limit": 10}

            print(f"\nQuerying: {url} ...")
            resp = client.get(url, params=params)
            if resp.status_code == 200:
                items = resp.json().get("items", [])
                print(f"-> Found {len(items)} record(s):")
                for w in items:
                    names = w.get("names", [])
                    if isinstance(names, dict):
                        names = names.get("items", [])
                    name = names[0].get("DisplayName") if names else "N/A"
                    print(f"   * PersonNumber: {w.get('PersonNumber')}")
                    print(f"     Name:         {name}")
                    print(f"     PersonId:     {w.get('PersonId')}")
                    print(f"     DOB:          {w.get('DateOfBirth')}")
                    print(f"     Created By:   {w.get('CreatedBy')}")
                    print()
            else:
                print(f"-> Error ({resp.status_code}): {resp.text[:300]}")

        elif choice == "2":
            limit_str = input("How many projects to list? (default 10): ").strip()
            limit = int(limit_str) if limit_str.isdigit() else 10
            url = f"{HOST_URL}/fscmRestApi/resources/11.13.18.05/projects"
            resp = client.get(url, params={"fields": "ProjectId,ProjectNumber,ProjectName,ProjectManagerName,ProjectStatus", "limit": limit})
            if resp.status_code == 200:
                projects = resp.json().get("items", [])
                print(f"\n-> Found {len(projects)} projects:")
                for p in projects:
                    print(f"   * Project #{p.get('ProjectNumber')} | '{p.get('ProjectName')}' | Status: {p.get('ProjectStatus')} | Mgr: {p.get('ProjectManagerName')} | ID: {p.get('ProjectId')}")
            else:
                print(f"-> Error ({resp.status_code}): {resp.text[:300]}")

        elif choice == "3":
            proj_id = input("Enter Project ID or Project Number (e.g., 300000040441155 or 101110): ").strip()
            if not proj_id:
                print("Project identifier is required.")
                continue

            # If they entered a project number like 101110, resolve it first
            if len(proj_id) < 10:
                lookup_resp = client.get(f"{HOST_URL}/fscmRestApi/resources/11.13.18.05/projects", params={"q": f"ProjectNumber='{proj_id}'"})
                if lookup_resp.status_code == 200 and lookup_resp.json().get("items"):
                    p_obj = lookup_resp.json()["items"][0]
                    proj_id = str(p_obj["ProjectId"])
                    print(f"Resolved Project Number '{p_obj['ProjectNumber']}' to ProjectId '{proj_id}' ({p_obj.get('ProjectName')})")
                else:
                    print(f"Could not find project with ProjectNumber '{proj_id}'.")
                    continue

            # Tasks
            task_resp = client.get(f"{HOST_URL}/fscmRestApi/resources/11.13.18.05/projects/{proj_id}/child/Tasks")
            if task_resp.status_code == 200:
                tasks = task_resp.json().get("items", [])
                print(f"\n-> Tasks ({len(tasks)} found):")
                for t in tasks:
                    print(f"   * Task #{t.get('TaskNumber')}: '{t.get('TaskName')}' (ID: {t.get('TaskId')})")
            else:
                print(f"-> Tasks error ({task_resp.status_code}): {task_resp.text[:200]}")

            # Team Members
            tm_resp = client.get(f"{HOST_URL}/fscmRestApi/resources/11.13.18.05/projects/{proj_id}/child/ProjectTeamMembers")
            if tm_resp.status_code == 200:
                members = tm_resp.json().get("items", [])
                print(f"\n-> Team Members ({len(members)} found):")
                for m in members:
                    print(f"   * {m.get('PersonName')} (Role: {m.get('ProjectRole')}, Email: {m.get('Email')})")
            else:
                print(f"-> Team Members error ({tm_resp.status_code}): {tm_resp.text[:200]}")

        elif choice == "4":
            emp_no = input("Enter Person Number (optional, leave blank for all): ").strip()
            params = {"limit": 10}
            if emp_no:
                params["q"] = f"Employee_Number_c='{emp_no}'"
            url = f"{HOST_URL}/hcmRestApi/resources/11.13.18.05/timeRecordEventRequests"
            resp = client.get(url, params=params)
            if resp.status_code == 200:
                items = resp.json().get("items", [])
                print(f"\n-> Retrieved {len(items)} timecard event request(s):")
                for item in items:
                    print(f"   * Request ID: {item.get('timeRecordEventRequestId')} | Mode: {item.get('processMode')} | Inline: {item.get('processInline')}")
            else:
                print(f"-> Error ({resp.status_code}): {resp.text[:300]}")

        elif choice == "5":
            endpoint = input("Enter endpoint path (e.g. /hcmRestApi/resources/11.13.18.05/workers): ").strip()
            if not endpoint.startswith("/"):
                endpoint = "/" + endpoint
            url = f"{HOST_URL}{endpoint}"
            print(f"GET {url}")
            resp = client.get(url, params={"limit": 3})
            print(f"Status Code: {resp.status_code}")
            try:
                print(json.dumps(resp.json(), indent=2)[:1500])
            except Exception:
                print(resp.text[:1500])

if __name__ == "__main__":
    main()
