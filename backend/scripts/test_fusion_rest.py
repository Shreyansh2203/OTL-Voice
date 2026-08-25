import os
import sys
import urllib.parse
import httpx
from dotenv import load_dotenv
load_dotenv()
USERNAME = os.getenv("OTL_SERVICE_USERNAME", "").strip()
PASSWORD = os.getenv("OTL_SERVICE_PASSWORD", "")
DEFAULT_OTL_URL = os.getenv("OTL_BASE_URL", "")
if not DEFAULT_OTL_URL:
    print("Error: OTL_BASE_URL environment variable is not set. Please configure it in .env")
    sys.exit(1)
parsed = urllib.parse.urlparse(DEFAULT_OTL_URL)
HOST_URL = f"{parsed.scheme}://{parsed.netloc}"
client = httpx.Client(
    auth=(USERNAME, PASSWORD),
    timeout=30.0,
    headers={"Accept": "application/json", "Accept-Encoding": "gzip"},
)
def run_suite():
    print("=" * 60)
    print("Oracle Fusion REST Data Extraction Test")
    print(f"Host: {HOST_URL}")
    print(f"User: {USERNAME}")
    print("=" * 60)
    print("\n[1] Querying Employees (/hcmRestApi/resources/11.13.18.05/workers)...")
    resp = client.get(
        f"{HOST_URL}/hcmRestApi/resources/11.13.18.05/workers",
        params={"expand": "names", "limit": 5}
    )
    if resp.status_code == 200:
        items = resp.json().get("items", [])
        print(f"-> SUCCESS: Retrieved {len(items)} workers.")
        for w in items:
            names = w.get("names", [])
            if isinstance(names, dict):
                names = names.get("items", [])
            name = names[0].get("DisplayName") if names else "N/A"
            print(f"   * Person #{w.get('PersonNumber')}: {name} (PersonId: {w.get('PersonId')})")
    else:
        print(f"-> FAILED ({resp.status_code}): {resp.text[:200]}")
    print("\n[2] Querying Projects & Child Tasks (/fscmRestApi/resources/11.13.18.05/projects)...")
    proj_resp = client.get(
        f"{HOST_URL}/fscmRestApi/resources/11.13.18.05/projects",
        params={"fields": "ProjectId,ProjectNumber,ProjectName,ProjectManagerName", "limit": 3}
    )
    if proj_resp.status_code == 200:
        projects = proj_resp.json().get("items", [])
        print(f"-> SUCCESS: Retrieved {len(projects)} projects.")
        for p in projects:
            p_id = p.get("ProjectId")
            print(f"\n   Project #{p.get('ProjectNumber')} - {p.get('ProjectName')} (ID: {p_id})")
            task_resp = client.get(f"{HOST_URL}/fscmRestApi/resources/11.13.18.05/projects/{p_id}/child/Tasks", params={"limit": 4})
            if task_resp.status_code == 200:
                tasks = task_resp.json().get("items", [])
                print(f"     Tasks ({len(tasks)} found):")
                for t in tasks:
                    print(f"       - Task #{t.get('TaskNumber')}: {t.get('TaskName')}")
            tm_resp = client.get(f"{HOST_URL}/fscmRestApi/resources/11.13.18.05/projects/{p_id}/child/ProjectTeamMembers")
            if tm_resp.status_code == 200:
                members = tm_resp.json().get("items", [])
                if members:
                    print(f"     Team Members ({len(members)} found):")
                    for m in members:
                        print(f"       - {m.get('PersonName')} ({m.get('ProjectRole')})")
    else:
        print(f"-> FAILED ({proj_resp.status_code}): {proj_resp.text[:200]}")
    print("\n[3] Querying Timecard Events (/hcmRestApi/resources/11.13.18.05/timeRecordEventRequests)...")
    otl_resp = client.get(
        f"{HOST_URL}/hcmRestApi/resources/11.13.18.05/timeRecordEventRequests",
        params={"limit": 3}
    )
    if otl_resp.status_code == 200:
        tc = otl_resp.json().get("items", [])
        print(f"-> SUCCESS: Retrieved {len(tc)} recent timecard requests.")
        for item in tc:
            print(f"   * Request ID: {item.get('timeRecordEventRequestId')}, Mode: {item.get('processMode')}")
    else:
        print(f"-> FAILED ({otl_resp.status_code}): {otl_resp.text[:200]}")
    print("\n" + "=" * 60)
    print("Test Complete.")
    print("=" * 60)
if __name__ == "__main__":
    run_suite()