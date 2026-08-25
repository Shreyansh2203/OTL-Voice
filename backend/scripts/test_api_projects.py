import os
import httpx
from dotenv import load_dotenv
load_dotenv()
USERNAME = os.getenv("OTL_SERVICE_USERNAME", "").strip()
PASSWORD = os.getenv("OTL_SERVICE_PASSWORD", "")
BASE_URL = os.getenv("OTL_BASE_URL", "")
host = BASE_URL.split("/hcmRestApi")[0]
client = httpx.Client(
    auth=(USERNAME, PASSWORD),
    timeout=30.0,
    headers={"Accept": "application/json"}
)
print("Testing ProjectTeamMembers globally...")
resp = client.get(f"{host}/fscmRestApi/resources/11.13.18.05/projectTeamMembers", params={"limit": 1})
print(f"Status: {resp.status_code}")
if resp.status_code == 200:
    print(resp.json())
else:
    print(resp.text)
print("\nTesting Projects query by TeamMember...")
resp2 = client.get(f"{host}/fscmRestApi/resources/11.13.18.05/projects", params={"q": "TeamMembers.PersonName='Prathmesh Nayadkar'", "limit": 1})
print(f"Status: {resp2.status_code}")
if resp2.status_code == 200:
    print("Items:", len(resp2.json().get("items", [])))
else:
    print(resp2.text)