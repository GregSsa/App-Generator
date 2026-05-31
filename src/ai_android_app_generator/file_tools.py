"""In-memory file inspection tools available to OpenAI agents."""

from __future__ import annotations

from typing import Any

MAX_FILE_CHARS = 64_000
MAX_SEARCH_MATCHES = 20


def execute_file_tool_requests(
    project_files: dict[str, str],
    tool_requests: Any,
) -> list[dict[str, Any]]:
    if not isinstance(tool_requests, list):
        return []

    results: list[dict[str, Any]] = []
    for request in tool_requests:
        if not isinstance(request, dict):
            continue
        tool_name = str(request.get("tool", "")).strip()
        if tool_name == "list_project_files":
            results.append({"tool": tool_name, "files": list_project_files(project_files)})
        elif tool_name == "read_project_files":
            results.append(
                {
                    "tool": tool_name,
                    "files": read_project_files(project_files, request.get("paths", [])),
                }
            )
        elif tool_name == "search_project_files":
            results.append(
                {
                    "tool": tool_name,
                    "matches": search_project_files(project_files, str(request.get("query", ""))),
                }
            )
        else:
            results.append({"tool": tool_name or "unknown", "error": "Unsupported file tool."})
    return results


def list_project_files(project_files: dict[str, str]) -> list[str]:
    return sorted(project_files.keys())


def read_project_files(project_files: dict[str, str], paths: Any) -> dict[str, str]:
    if not isinstance(paths, list):
        return {}

    selected: dict[str, str] = {}
    for path in paths:
        if not isinstance(path, str) or path not in project_files:
            continue
        content = project_files[path]
        selected[path] = content[:MAX_FILE_CHARS]
    return selected


def search_project_files(project_files: dict[str, str], query: str) -> list[dict[str, Any]]:
    query = query.strip()
    if not query:
        return []

    matches: list[dict[str, Any]] = []
    lowered_query = query.lower()
    for path, content in sorted(project_files.items()):
        for line_number, line in enumerate(content.splitlines(), start=1):
            if lowered_query in line.lower():
                matches.append({"file": path, "line": line_number, "text": line[:240]})
                if len(matches) >= MAX_SEARCH_MATCHES:
                    return matches
    return matches
