from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from .oci_genai import GenAIChatClient
from .otl_client import _business_timezone
from ..core.config import is_demo_mode

PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "prompt.txt"


@lru_cache(maxsize=1)
def _client() -> GenAIChatClient:
    return GenAIChatClient()


def _safe_err(msg: str | Exception) -> str:
    return " ".join(str(msg).split())[:200]


def load_prompt_template() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def render_assignments(work_orders: list[dict[str, Any]]) -> str:
    if not work_orders:
        return (
            "This employee has no project assignments on record. Tell them to "
            "contact their manager; do not invent a project or work order."
        )
    lines: list[str] = []
    for order in work_orders:
        description = order.get("description")
        if description:
            description = _sanitize_template_value(description)
        suffix = f" - {description}" if description else ""
        lines.append(f"Work Order {order.get('workOrder')}{suffix}")
        for project in order.get("projects", []):
            proj_id = project.get("projectId")
            id_str = f" [ID: {proj_id}]" if proj_id else ""
            proj_name = _sanitize_template_value(project.get("projectName", ""))
            lines.append(f"  Project {project.get('projectNo')}: {proj_name}{id_str}")
            for task in project.get("tasks", []):
                t_id = task.get("taskId")
                t_id_str = f" [ID: {t_id}]" if t_id else ""
                task_details = _sanitize_template_value(task.get("taskDetails", ""))
                lines.append(f"    - {task_details}{t_id_str}")
    return "\n".join(lines)


def _sanitize_template_value(value: str) -> str:
    if not value:
        return "not provided"
    sanitized = str(value).replace("{{", "").replace("}}", "")
    return sanitized[:500]


def _sanitize_assignments(text: str) -> str:
    if not text:
        return text
    return text.replace("{{", "").replace("}}", "")[:4000]


def build_system_prompt(
    username: str,
    employee_id: str,
    employee_name: str,
    assignments: list[dict[str, Any]] | None = None,
    recent_history: str = "",
) -> str:
    date_str = datetime.now(_business_timezone()).strftime("%A, %Y-%m-%d")
    prompt = load_prompt_template()
    prompt = prompt.replace("{{USERNAME}}", _sanitize_template_value(username))
    prompt = prompt.replace(
        "{{EMPLOYEE_NUMBER}}", _sanitize_template_value(employee_id)
    )
    prompt = prompt.replace(
        "{{EMPLOYEE_NAME}}", _sanitize_template_value(employee_name)
    )
    prompt = prompt.replace("{{CURRENT_DATE}}", date_str)
    prompt = prompt.replace(
        "{{ASSIGNMENTS}}", _sanitize_assignments(render_assignments(assignments or []))
    )
    prompt = prompt.replace(
        "{{RECENT_HISTORY}}",
        _sanitize_template_value(recent_history)
        if recent_history
        else "No recent history available.",
    )
    return prompt


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def _demo_entries() -> list[dict]:
    today = datetime.now(_business_timezone()).date().isoformat()
    return [
        {
            "employeeNumber": "DEMO-0001",
            "employeeName": "Demo User",
            "projectId": "900001",
            "projectNo": "D-1001",
            "projectName": "Aurora Field Trial",
            "workOrder": "WO-D-1001",
            "taskId": "81001",
            "taskDetails": "Field data collection",
            "hours": 8,
            "date": today,
            "payrollTimeType": "Regular",
            "expenditureType": "Regular Time",
            "currencyCode": "USD",
        }
    ]


_DEMO_REPLY = (
    "Demo mode — no Oracle or OCI credentials were used, and nothing was written "
    "anywhere.\n\n"
    "Here is a sample timecard proposal for **Aurora Field Trial** (project D-1001, "
    "work order WO-D-1001, task *Field data collection*): 8 hours today.\n\n"
    "```json\n{{\"entries\": {entries}}}\n```\n\n"
    "Review the proposal and submit it to exercise the approval flow — the write "
    "against Oracle is replaced with a canned success response in demo mode."
)


def _demo_stream() -> Iterator[str]:
    import json as _json

    entries = _demo_entries()
    reply = _DEMO_REPLY.format(entries=_json.dumps(entries, indent=2))
    # Emit in small chunks so the streaming UI renders it like a live model.
    chunk = 24
    for start in range(0, len(reply), chunk):
        yield _sse({"delta": reply[start : start + chunk]})
    yield _sse({"done": True})


def stream_sse(system_prompt: str, history: list[dict]) -> Iterator[str]:
    if is_demo_mode():
        yield from _demo_stream()
        return
    try:
        client = _client()
    except Exception as exc:
        yield _sse({"error": f"Model unavailable: {_safe_err(exc)}"})
        return
    try:
        for delta in client.stream(system_prompt, history):
            if delta:
                yield _sse({"delta": delta})
    except Exception as exc:
        yield _sse({"error": _safe_err(exc)})
        return
    yield _sse({"done": True})
