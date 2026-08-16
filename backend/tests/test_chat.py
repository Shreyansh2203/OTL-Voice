import pytest
from unittest.mock import patch, MagicMock
import json

from backend.services.chat import (
    render_assignments,
    _client,
    load_prompt_template,
    build_system_prompt,
    _sse,
    stream_sse,
)

def test_render_assignments():
    work_orders = [
        {
            "workOrder": "WO1",
            "description": "Desc1",
            "projects": [
                {
                    "projectId": "1",
                    "projectNo": "P1",
                    "projectName": "Project1",
                    "tasks": [{"taskId": "T1", "taskDetails": "Task1"}]
                }
            ]
        }
    ]
    output = render_assignments(work_orders)
    assert "WO1 - Desc1" in output
    assert "Project P1: Project1" in output
    assert "- Task1" in output

def test_render_assignments_empty():
    output = render_assignments([])
    assert "no project assignments" in output

@patch("backend.services.chat.GeminiChatClient")
def test_client(mock_client):
    _client.cache_clear()
    client = _client()
    assert client is not None
    mock_client.assert_called_once()

@patch("backend.services.chat.PROMPT_PATH")
def test_load_prompt_template(mock_prompt_path):
    load_prompt_template.cache_clear()
    mock_prompt_path.read_text.return_value = "Prompt {{USERNAME}}"
    prompt = load_prompt_template()
    assert prompt == "Prompt {{USERNAME}}"
    mock_prompt_path.read_text.assert_called_once_with(encoding="utf-8")

@patch("backend.services.chat.load_prompt_template")
@patch("backend.services.chat.datetime")
def test_build_system_prompt(mock_datetime, mock_load):
    mock_load.return_value = "{{USERNAME}} {{EMPLOYEE_NUMBER}} {{EMPLOYEE_NAME}} {{CURRENT_DATE}} {{ASSIGNMENTS}}"
    mock_datetime.now.return_value.strftime.return_value = "Monday, 2026-01-01"
    
    prompt = build_system_prompt("john_doe", "123", "John Doe")
    assert "john_doe" in prompt
    assert "123" in prompt
    assert "John Doe" in prompt
    assert "Monday, 2026-01-01" in prompt
    assert "no project assignments" in prompt

    prompt = build_system_prompt("", "", "", [{"workOrder": "WO2"}])
    assert "not provided" in prompt
    assert "WO2" in prompt

def test_sse():
    res = _sse({"msg": "hello"})
    assert res == 'data: {"msg": "hello"}\n\n'

@patch("backend.services.chat._client")
def test_stream_sse_success(mock_client_func):
    mock_client = MagicMock()
    mock_client.stream.return_value = iter(["chunk1", "", "chunk2"])
    mock_client_func.return_value = mock_client
    
    gen = stream_sse("sys prompt", [{"role": "user"}])
    chunks = list(gen)
    assert len(chunks) == 3
    assert '{"delta": "chunk1"}' in chunks[0]
    assert '{"delta": "chunk2"}' in chunks[1]
    assert '{"done": true}' in chunks[2]

@patch("backend.services.chat._client")
def test_stream_sse_client_error(mock_client_func):
    mock_client_func.side_effect = Exception("Client down")
    
    gen = stream_sse("sys prompt", [])
    chunks = list(gen)
    assert len(chunks) == 1
    assert '{"error": "Model unavailable: Client down"}' in chunks[0]

@patch("backend.services.chat._client")
def test_stream_sse_stream_error(mock_client_func):
    mock_client = MagicMock()
    mock_client.stream.side_effect = Exception("Stream error")
    mock_client_func.return_value = mock_client
    
    gen = stream_sse("sys prompt", [])
    chunks = list(gen)
    assert len(chunks) == 1
    assert '{"error": "Stream error"}' in chunks[0]

