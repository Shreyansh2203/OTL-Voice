
from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from .oci_gemini import GeminiChatClient

PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "prompt.txt"


@lru_cache(maxsize=1)
def _client() -> GeminiChatClient:
    return GeminiChatClient()


def _safe_err(msg: str | Exception) -> str:
    """Sanitize an exception message before sending it to the client.

    Strips newlines/control characters and truncates so verbose upstream
    (OCI) error strings cannot leak request identifiers or stack detail.
    """
    return " ".join(str(msg).split())[:200]


def load_prompt_template() -> str:
    """Load the prompt template from file (not cached, allows live reload)."""
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
        suffix = f" - {description}" if description else ""
        lines.append(f"Work Order {order.get('workOrder')}{suffix}")
        for project in order.get("projects", []):
            proj_id = project.get("projectId")
            id_str = f" [ID: {proj_id}]" if proj_id else ""
            lines.append(
                f"  Project {project.get('projectNo')}: {project.get('projectName')}{id_str}"
            )
            for task in project.get("tasks", []):
                t_id = task.get("taskId")
                t_id_str = f" [ID: {t_id}]" if t_id else ""
                lines.append(f"    - {task.get('taskDetails')}{t_id_str}")
    return "\n".join(lines)


def _sanitize_template_value(value: str) -> str:
    """Sanitize a value before injecting into the system prompt to prevent prompt injection."""
    if not value:
        return "not provided"
    # Remove potential injection patterns
    sanitized = value.replace("{{", "").replace("}}", "")
    # Limit length to prevent token overflow
    return sanitized[:500]


def _sanitize_assignments(text: str) -> str:
    """Sanitize catalogue-derived assignment text before prompt injection.

    Assignment names/comments originate from Fusion and could contain
    template tokens or injection phrasing; strip those and cap the length.
    """
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
    date_str = datetime.now(UTC).strftime("%A, %Y-%m-%d")

    prompt = load_prompt_template()
    prompt = prompt.replace("{{USERNAME}}", _sanitize_template_value(username))
    prompt = prompt.replace("{{EMPLOYEE_NUMBER}}", _sanitize_template_value(employee_id))
    prompt = prompt.replace("{{EMPLOYEE_NAME}}", _sanitize_template_value(employee_name))
    prompt = prompt.replace("{{CURRENT_DATE}}", date_str)
    prompt = prompt.replace("{{ASSIGNMENTS}}", _sanitize_assignments(render_assignments(assignments or [])))
    prompt = prompt.replace("{{RECENT_HISTORY}}", _sanitize_template_value(recent_history) if recent_history else "No recent history available.")
    return prompt


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def stream_sse(system_prompt: str, history: list[dict]) -> Iterator[str]:
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
