import json

d = json.load(open("data/fusion_person_master.json", "r", encoding="utf-8"))
with_projects = [p for p in d["persons"] if p["total_assigned_projects"] > 0]
total = len(d["persons"])

print(f"Employees WITH projects: {len(with_projects)} out of {total}")
print()

for p in with_projects[:8]:
    print(f"  {p['employee_number']} - {p['full_name']} ({p['total_assigned_projects']} projects)")
    for proj in p["assigned_projects"][:2]:
        tasks_str = ", ".join(t["task_name"] for t in proj["tasks"][:3]) or "No tasks"
        print(f"    -> #{proj['project_number']}: {proj['project_name']} [{proj['role']}]")
        print(f"       Tasks: {tasks_str}")
