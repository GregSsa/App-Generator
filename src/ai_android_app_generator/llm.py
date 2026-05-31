"""Optional OpenAI helpers for workflow agents."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from .file_tools import execute_file_tool_requests, list_project_files


class OpenAIUnavailable(RuntimeError):
    """Raised when an OpenAI-backed agent cannot run."""


def ask_openai_agent(
    agent_name: str,
    system_prompt: str,
    payload: dict[str, Any],
    project_files: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run one OpenAI-backed agent and parse its JSON response."""

    _load_dotenv()

    if not os.getenv("OPENAI_API_KEY"):
        raise OpenAIUnavailable("OPENAI_API_KEY is not configured.")

    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        raise OpenAIUnavailable("Install the OpenAI extra with `pip install -e .[openai]`.") from exc

    model_name = os.getenv("OPENAI_MODEL", "gpt-5-mini")
    timeout = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "25"))
    model = ChatOpenAI(model=model_name, timeout=timeout, max_retries=1)
    files = project_files or {}
    agent_payload = _with_file_tool_context(payload, files)
    messages = [
        (
            "system",
            f"{system_prompt}\n\n"
            "Return only one valid JSON object. Do not wrap it in markdown. "
            f'Include an "agent" field with value "{agent_name}".\n\n'
            "You may inspect generated project files before your final answer. "
            'To request files, return JSON with "tool_requests": a list of objects. '
            'Supported tools: {"tool":"list_project_files"}, '
            '{"tool":"read_project_files","paths":["app/build.gradle.kts"]}, '
            '{"tool":"search_project_files","query":"jvmToolchain"}. '
            "If you request tools, do not include your final plan yet; wait for tool_results.",
        ),
        ("human", json.dumps(agent_payload, ensure_ascii=True, indent=2)),
    ]

    _verbose(f"[openai] {agent_name} request started")
    response = model.invoke(messages)
    parsed = _response_to_json(response)

    tool_results = execute_file_tool_requests(files, parsed.get("tool_requests"))
    if tool_results:
        _verbose(f"[openai] {agent_name} tool follow-up started")
        response = model.invoke(
            messages
            + [
                ("assistant", json.dumps(parsed, ensure_ascii=True)),
                (
                    "human",
                    json.dumps(
                        {
                            "tool_results": tool_results,
                            "instruction": "Use these inspected file contents to return your final JSON response now.",
                        },
                        ensure_ascii=True,
                        indent=2,
                    ),
                ),
            ]
        )
        parsed = _response_to_json(response)

    _verbose(f"[openai] {agent_name} request completed")
    return parsed


def _response_to_json(response: Any) -> dict[str, Any]:

    content = getattr(response, "content", "")
    if isinstance(content, list):
        content = "".join(str(part) for part in content)
    return _parse_json_object(str(content))


def _with_file_tool_context(payload: dict[str, Any], project_files: dict[str, str]) -> dict[str, Any]:
    if not project_files:
        return payload

    return {
        **payload,
        "file_tools": {
            "available_files": list_project_files(project_files),
            "note": "Request specific files with tool_requests instead of guessing from filenames.",
        },
    }


def _parse_json_object(content: str) -> dict[str, Any]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, flags=re.DOTALL)
        if not match:
            raise OpenAIUnavailable("OpenAI response did not contain JSON.")
        parsed = json.loads(match.group(0))

    if not isinstance(parsed, dict):
        raise OpenAIUnavailable("OpenAI response JSON must be an object.")
    return parsed


def _load_dotenv(path: Path | None = None) -> None:
    env_path = path or Path(".env")
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _verbose(message: str) -> None:
    if os.getenv("AI_GENERATOR_VERBOSE") == "1":
        print(message)
