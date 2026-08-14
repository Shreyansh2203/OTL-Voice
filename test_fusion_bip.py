import base64
import csv
import json
import os
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

# Ensure UTF-8 output in Windows terminals
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Force load .env from the project root regardless of current working directory
project_root = Path(__file__).resolve().parent
env_path = project_root / ".env"
data_dir = project_root / "data"
data_dir.mkdir(parents=True, exist_ok=True)

try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=env_path)
except ImportError:
    pass

try:
    import httpx
except ImportError:
    print("\n[ERROR] 'httpx' is not installed in your active Python environment.")
    print("Please install it using:\n   pip install httpx python-dotenv\n")
    sys.exit(1)

USERNAME = os.getenv("OTL_SERVICE_USERNAME", "").strip()
PASSWORD = os.getenv("OTL_SERVICE_PASSWORD", "")
DEFAULT_OTL_URL = os.getenv(
    "OTL_BASE_URL",
    "https://fa-epxp-test-saasfaprod1.fa.ocs.oraclecloud.com/hcmRestApi/resources/11.13.18.05/timeRecordEventRequests"
)

if not USERNAME or not PASSWORD:
    print(f"\n[ERROR] Credentials missing in {env_path}")
    print("Please ensure OTL_SERVICE_USERNAME and OTL_SERVICE_PASSWORD are set in your .env file.\n")
    sys.exit(1)

parsed = urllib.parse.urlparse(DEFAULT_OTL_URL)
HOST_URL = f"{parsed.scheme}://{parsed.netloc}"
REPORT_PATH = "/Custom/EmployeeSyncReport.xdo"
ENDPOINT_URL = f"{HOST_URL}/xmlpserver/services/v2/ReportService"

print("=" * 70)
print(" Oracle BI Publisher - Bulk Employee Data Extraction & Export")
print(f" Target Host: {HOST_URL}")
print(f" User:        {USERNAME}")
print(f" Report Path: {REPORT_PATH}")
print("=" * 70)

soap_body = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:v2="http://xmlns.oracle.com/oxp/service/v2">
   <soapenv:Header/>
   <soapenv:Body>
      <v2:runReport>
         <v2:reportRequest>
            <v2:attributeFormat>xml</v2:attributeFormat>
            <v2:attributeLocale>en-US</v2:attributeLocale>
            <v2:reportAbsolutePath>{REPORT_PATH}</v2:reportAbsolutePath>
         </v2:reportRequest>
         <v2:userID>{USERNAME}</v2:userID>
         <v2:password>{PASSWORD}</v2:password>
      </v2:runReport>
   </soapenv:Body>
</soapenv:Envelope>"""

headers = {
    "Content-Type": "text/xml;charset=UTF-8",
    "SOAPAction": '""',
}

print(f"\nConnecting to Oracle BI Publisher at:\n  {ENDPOINT_URL} ...")

try:
    with httpx.Client(timeout=60.0) as client:
        resp = client.post(ENDPOINT_URL, content=soap_body.encode("utf-8"), headers=headers)
except Exception as exc:
    print(f"\n[ERROR] Network connection failed: {exc}\n")
    sys.exit(1)

if resp.status_code != 200:
    print(f"\n[ERROR] Oracle returned HTTP {resp.status_code}:")
    print(resp.text[:600])
    sys.exit(1)

try:
    root = ET.fromstring(resp.text)
    report_bytes_elem = None
    for elem in root.iter():
        if elem.tag.endswith("reportBytes") or elem.tag == "reportBytes":
            report_bytes_elem = elem
            break

    if report_bytes_elem is None or not report_bytes_elem.text:
        print("\n[ERROR] Report executed, but no <reportBytes> found in response payload:")
        print(resp.text[:500])
        sys.exit(1)

    raw_xml = base64.b64decode(report_bytes_elem.text).decode("utf-8", errors="replace")
    data_root = ET.fromstring(raw_xml)
    rows = data_root.findall(".//G_1")

    records = []
    for row in rows:
        records.append({
            "employee_number": (row.findtext("EMPLOYEE_NUMBER") or "").strip(),
            "person_id": (row.findtext("HCM_PERSON_ID") or "").strip(),
            "full_name": (row.findtext("EMPLOYEE_NAME") or "").strip(),
            "created_by": (row.findtext("CREATED_BY") or "").strip(),
        })

    print(f"\n[SUCCESS] Extracted and parsed {len(records)} employee records from Oracle Fusion in ~2s!\n")

    # 1. Save to JSON
    json_path = data_dir / "fusion_employees.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)

    # 2. Save to CSV
    csv_path = data_dir / "fusion_employees.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["employee_number", "person_id", "full_name", "created_by"])
        writer.writeheader()
        writer.writerows(records)

    print("=" * 70)
    print(" FILES SAVED SUCCESSFULLY:")
    print(f"  * JSON: {json_path}")
    print(f"  * CSV:  {csv_path}")
    print("=" * 70)

    print("\nPreview of first 10 employees:")
    print(f"{'Emp #':<15} | {'Person ID':<18} | {'Employee Name':<30} | {'Created By'}")
    print("-" * 85)
    for r in records[:10]:
        print(f"{r['employee_number']:<15} | {r['person_id']:<18} | {r['full_name']:<30} | {r['created_by']}")
    print("-" * 85)
    print(f"Total Employees: {len(records)}\n")

except Exception as exc:
    print(f"\n[ERROR] Failed while processing records: {exc}")
    import traceback
    traceback.print_exc()
