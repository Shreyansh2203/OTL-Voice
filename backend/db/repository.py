
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .connection import get_conn
from .passwords import verify_password


@dataclass(frozen=True)
class Employee:

    employee_id: str  # -> Employee_Number_c
    username: str
    full_name: str  # -> Employee_Name_c


def _employee(row) -> Employee:
    return Employee(
        employee_id=row["employee_id"],
        username=row["username"],
        full_name=row["full_name"],
    )


#: Well-formed but unmatchable hash, used so an unknown username still performs a
#: full PBKDF2 derivation. The base64 must be valid or ``verify_password`` bails
#: out early and the timing difference reappears.
_DUMMY_HASH = (
    "pbkdf2_sha256$600000$"
    "AAAAAAAAAAAAAAAAAAAAAA==$"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
)


# --------------------------------------------------------------------------- #
# Employees / auth
# --------------------------------------------------------------------------- #
def verify_login(username: str, password: str) -> Optional[Employee]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT employee_id, username, full_name, password_hash"
            " FROM employees WHERE username = ? AND is_active = 1",
            (username.strip(),),
        ).fetchone()

    stored = row["password_hash"] if row else _DUMMY_HASH
    if not verify_password(password, stored) or row is None:
        return None
    return _employee(row)


def get_employee(employee_id: str) -> Optional[Employee]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT employee_id, username, full_name FROM employees"
            " WHERE employee_id = ? AND is_active = 1",
            (str(employee_id),),
        ).fetchone()
    return _employee(row) if row else None


# --------------------------------------------------------------------------- #
# Labour catalogue
# --------------------------------------------------------------------------- #
def resolve_project(project_no: int) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT project_no, work_order, project_name FROM projects"
            " WHERE project_no = ? AND is_active = 1",
            (int(project_no),),
        ).fetchone()
    if row is None:
        return None
    return {
        "projectNo": row["project_no"],
        "workOrder": row["work_order"],
        "projectName": row["project_name"],
    }


def find_project_by_name(name: str) -> Optional[Dict[str, Any]]:
    cleaned = (name or "").strip()
    if not cleaned:
        return None
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT project_no, work_order, project_name FROM projects"
            " WHERE project_name = ? COLLATE NOCASE AND is_active = 1 LIMIT 2",
            (cleaned,),
        ).fetchall()
    if len(rows) != 1:
        return None
    row = rows[0]
    return {
        "projectNo": row["project_no"],
        "workOrder": row["work_order"],
        "projectName": row["project_name"],
    }


def list_project_tasks(project_no: int) -> List[str]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT task_details FROM project_tasks"
            " WHERE project_no = ? AND is_active = 1 ORDER BY task_id",
            (int(project_no),),
        ).fetchall()
    return [row["task_details"] for row in rows]


# --------------------------------------------------------------------------- #
# Assignments
# --------------------------------------------------------------------------- #
def is_assigned(employee_id: str, project_no: int) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM assignments a JOIN projects p USING (project_no)"
            " WHERE a.employee_id = ? AND a.project_no = ? AND p.is_active = 1",
            (str(employee_id), int(project_no)),
        ).fetchone()
    return row is not None


def list_assignments(employee_id: str) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT v.work_order, w.description, v.project_no, v.project_name, v.task_details"
            " FROM v_employee_labour v"
            " LEFT JOIN work_orders w ON w.work_order = v.work_order"
            " WHERE v.employee_id = ?"
            " ORDER BY v.work_order, v.project_no, v.task_id",
            (str(employee_id),),
        ).fetchall()

    orders: Dict[str, Dict[str, Any]] = {}
    projects: Dict[int, Dict[str, Any]] = {}

    for row in rows:
        order = orders.setdefault(
            row["work_order"],
            {
                "workOrder": row["work_order"],
                "description": row["description"],
                "projects": [],
            },
        )
        project = projects.get(row["project_no"])
        if project is None:
            project = {
                "projectNo": row["project_no"],
                "projectName": row["project_name"],
                "tasks": [],
            }
            projects[row["project_no"]] = project
            order["projects"].append(project)
        # LEFT JOIN: a project with no tasks yields one row with a NULL task.
        if row["task_details"] is not None:
            project["tasks"].append(row["task_details"])

    return list(orders.values())


def assigned_project_numbers(employee_id: str) -> List[int]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT a.project_no FROM assignments a JOIN projects p USING (project_no)"
            " WHERE a.employee_id = ? AND p.is_active = 1 ORDER BY a.project_no",
            (str(employee_id),),
        ).fetchall()
    return [row["project_no"] for row in rows]
