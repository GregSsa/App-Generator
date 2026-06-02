"""Optional OpenAI helpers for workflow agents."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from .file_tools import list_project_files
from .mcp_filesystem import execute_mcp_file_tool_requests


class OpenAIUnavailable(RuntimeError):
    """Raised when an OpenAI-backed agent cannot run."""


class InvalidOpenAIJSON(OpenAIUnavailable):
    """Raised when an OpenAI response cannot be parsed as a JSON object."""

    def __init__(self, message: str, content: str) -> None:
        super().__init__(message)
        self.content = content


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
    model = ChatOpenAI(model=model_name, max_retries=1)
    files = project_files or {}
    agent_payload = _with_file_tool_context(payload, files)
    messages = [
        (
            "system",
            f"{system_prompt}\n\n"
            "Return only one valid JSON object. Do not wrap it in markdown. "
            f'Include an "agent" field with value "{agent_name}".\n\n'
            "You may inspect generated project files before your final answer through the Filesystem MCP Server. "
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
    parsed = _response_to_json_with_repair(model, messages, response, agent_name)

    tool_results = execute_mcp_file_tool_requests(files, parsed.get("tool_requests"))
    if tool_results:
        _verbose(f"[openai] {agent_name} tool follow-up started")
        follow_up_messages = messages + [
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
        response = model.invoke(follow_up_messages)
        parsed = _response_to_json_with_repair(model, follow_up_messages, response, agent_name)

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
                "backend": "filesystem_mcp_server",
                "note": "Request specific files with tool_requests instead of guessing from filenames. Requests are executed through a Filesystem MCP Server on a temporary project snapshot.",
            },
        }


def _parse_json_object(content: str) -> dict[str, Any]:
    content = _strip_markdown_fence(content.strip())
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as first_error:
        candidate = _extract_json_object(content)
        if candidate is None:
            raise InvalidOpenAIJSON("OpenAI response did not contain JSON.", content) from first_error
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError as second_error:
            raise InvalidOpenAIJSON(f"OpenAI response was not valid JSON: {second_error}", content) from second_error

    if not isinstance(parsed, dict):
        raise OpenAIUnavailable("OpenAI response JSON must be an object.")
    return parsed


def _response_to_json_with_repair(
    model: Any,
    messages: list[tuple[str, str]],
    response: Any,
    agent_name: str,
) -> dict[str, Any]:
    try:
        return _response_to_json(response)
    except InvalidOpenAIJSON as exc:
        _verbose(f"[openai] {agent_name} JSON repair started")
        repair_response = model.invoke(
            messages
            + [
                ("assistant", exc.content),
                (
                    "human",
                    "Your previous answer was not valid JSON. "
                    f"Parser error: {exc}. "
                    "Return the same answer corrected as exactly one valid JSON object. "
                    "Do not add markdown, comments, or explanations.",
                ),
            ]
        )
        return _response_to_json(repair_response)


def _strip_markdown_fence(content: str) -> str:
    match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", content, flags=re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else content


def _extract_json_object(content: str) -> str | None:
    start = content.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(content)):
        char = content[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return content[start : index + 1]
    return None


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
