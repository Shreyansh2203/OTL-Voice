
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict

from .connection import db_path, get_conn, init_db, is_seeded
from .passwords import hash_password

SEED_PATH = Path(__file__).with_name("seed.json")

# Child-first, so foreign keys never block the delete.
_TABLES = ("assignments", "project_tasks", "projects", "work_orders", "employees")


def load_seed() -> Dict[str, Any]:
    return json.loads(SEED_PATH.read_text(encoding="utf-8"))


def clear(conn: sqlite3.Connection) -> None:
    for table in _TABLES:
        conn.execute(f"DELETE FROM {table}")
    # AUTOINCREMENT keeps a high-water mark per table; reset it so a reseed
    # produces the same task_ids every time.
    conn.execute("DELETE FROM sqlite_sequence WHERE name = 'project_tasks'")


def populate(conn: sqlite3.Connection, data: Dict[str, Any]) -> Dict[str, int]:
    counts = {"employees": 0, "work_orders": 0, "projects": 0, "tasks": 0, "assignments": 0}

    for employee in data.get("employees", []):
        conn.execute(
            "INSERT INTO employees (employee_id, username, password_hash, full_name, is_active)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                str(employee["employee_id"]),
                employee["username"],
                hash_password(employee["password"]),
                employee["full_name"],
                int(employee.get("is_active", 1)),
            ),
        )
        counts["employees"] += 1

    for order in data.get("work_orders", []):
        conn.execute(
            "INSERT INTO work_orders (work_order, description, is_active) VALUES (?, ?, ?)",
            (
                str(order["work_order"]),
                order.get("description"),
                int(order.get("is_active", 1)),
            ),
        )
        counts["work_orders"] += 1

    for project in data.get("projects", []):
        conn.execute(
            "INSERT INTO projects (project_no, work_order, project_name, is_active)"
            " VALUES (?, ?, ?, ?)",
            (
                int(project["project_no"]),
                str(project["work_order"]),
                project["project_name"],
                int(project.get("is_active", 1)),
            ),
        )
        counts["projects"] += 1

        for task in project.get("tasks", []):
            conn.execute(
                "INSERT INTO project_tasks (project_no, task_details) VALUES (?, ?)",
                (int(project["project_no"]), task),
            )
            counts["tasks"] += 1

    for assignment in data.get("assignments", []):
        conn.execute(
            "INSERT INTO assignments (employee_id, project_no) VALUES (?, ?)",
            (str(assignment["employee_id"]), int(assignment["project_no"])),
        )
        counts["assignments"] += 1

    return counts


def seed(*, force: bool = False) -> Dict[str, int]:
    init_db()
    if is_seeded() and not force:
        return {}

    data = load_seed()
    with get_conn(write=True) as conn:
        if force:
            clear(conn)
        return populate(conn, data)


def ensure_seeded() -> None:
    seed(force=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the OTL reference database.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="delete existing reference data and reload it from seed.json",
    )
    args = parser.parse_args()

    counts = seed(force=args.force)
    if not counts:
        print(f"{db_path()} is already populated; nothing to do (use --force to reload).")
        return
    summary = ", ".join(f"{n} {name}" for name, n in counts.items())
    print(f"Seeded {db_path()}: {summary}.")


if __name__ == "__main__":
    main()
