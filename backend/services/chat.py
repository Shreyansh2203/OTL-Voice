
from __future__ import annotations

import json
from datetime import datetime, UTC
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from .oci_gemini import GeminiChatClient

PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "prompt.txt"


@lru_cache(maxsize=1)
def _client() -> GeminiChatClient:
    return GeminiChatClient()


@lru_cache(maxsize=1)
def load_prompt_template() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def render_assignments(work_orders: List[Dict[str, Any]]) -> str:
    if not work_orders:
        return (
            "This employee has no project assignments on record. Tell them to "
            "contact their manager; do not invent a project or work order."
        )

    lines: List[str] = []
    for order in work_orders:
        description = order.get("description")
        suffix = f" - {description}" if description else ""
        lines.append(f"Work Order {order['workOrder']}{suffix}")
        for project in order.get("projects", []):
            lines.append(
                f"  Project {project['projectNo']}: {project['projectName']}"
            )
            for task in project.get("tasks", []):
                lines.append(f"    - {task}")
    return "\n".join(lines)


def build_system_prompt(
    username: str,
    employee_id: str,
    employee_name: str,
    assignments: Optional[List[Dict[str, Any]]] = None,
) -> str:
    date_str = datetime.now(UTC).strftime("%A, %Y-%m-%d")

    prompt = load_prompt_template()
    prompt = prompt.replace("{{USERNAME}}", username or "not provided")
    prompt = prompt.replace("{{EMPLOYEE_NUMBER}}", employee_id or "not provided")
    prompt = prompt.replace("{{EMPLOYEE_NAME}}", employee_name or "not provided")
    prompt = prompt.replace("{{CURRENT_DATE}}", date_str)
    prompt = prompt.replace("{{ASSIGNMENTS}}", render_assignments(assignments or []))
    return prompt


def _sse(obj: Dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def stream_sse(system_prompt: str, history: List[Dict]) -> Iterator[str]:
    try:
        client = _client()
    except Exception as exc:  # noqa: BLE001 - report init failure to the client
        yield _sse({"error": f"Model unavailable: {exc}"})
        return

    try:
        for delta in client.stream(system_prompt, history):
            if delta:
                yield _sse({"delta": delta})
    except Exception as exc:  # noqa: BLE001
        yield _sse({"error": str(exc)})
        return

    yield _sse({"done": True})
