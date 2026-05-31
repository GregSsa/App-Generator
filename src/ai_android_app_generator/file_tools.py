"""In-memory project tools available to OpenAI agents."""

from __future__ import annotations

from typing import Any

MAX_FILE_CHARS = 64_000
MAX_SEARCH_MATCHES = 20
MAX_PATCHES = 20


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


def apply_file_patches(
    project_files: dict[str, str],
    patch_requests: Any,
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """Apply safe, structured patches to generated project files."""

    if not isinstance(patch_requests, list):
        return project_files, []

    next_files = dict(project_files)
    results: list[dict[str, Any]] = []
    for patch in patch_requests[:MAX_PATCHES]:
        if not isinstance(patch, dict):
            continue
        operation = _normalize_patch_operation(patch)
        path = str(patch.get("path", "")).strip()

        if not _is_safe_project_path(path):
            results.append({"op": operation or "unknown", "path": path, "ok": False, "error": "Unsafe path."})
            continue

        if operation == "replace_text":
            old = patch.get("old")
            new = patch.get("new")
            if not isinstance(old, str) or not isinstance(new, str):
                results.append({"op": operation, "path": path, "ok": False, "error": "old and new must be strings."})
                continue
            content = next_files.get(path)
            if content is None or old not in content:
                results.append({"op": operation, "path": path, "ok": False, "error": "Target text not found."})
                continue
            next_files[path] = content.replace(old, new, 1)
            results.append({"op": operation, "path": path, "ok": True})
        elif operation == "upsert_file":
            content = patch.get("content")
            if not isinstance(content, str):
                results.append({"op": operation, "path": path, "ok": False, "error": "content must be a string."})
                continue
            next_files[path] = content
            results.append({"op": operation, "path": path, "ok": True})
        elif operation == "delete_file":
            existed = path in next_files
            next_files.pop(path, None)
            results.append({"op": operation, "path": path, "ok": True, "existed": existed})
        else:
            results.append({"op": operation or "unknown", "path": path, "ok": False, "error": "Unsupported patch op."})

    return next_files, results


def _normalize_patch_operation(patch: dict[str, Any]) -> str:
    raw_operation = (
        patch.get("op")
        or patch.get("operation")
        or patch.get("action")
        or patch.get("type")
        or patch.get("kind")
        or ""
    )
    operation = str(raw_operation).strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "add_file": "upsert_file",
        "create_file": "upsert_file",
        "write_file": "upsert_file",
        "update_file": "upsert_file",
        "modify_file": "upsert_file",
        "replace_file": "upsert_file",
        "upsert": "upsert_file",
        "replace": "replace_text",
        "replace_in_file": "replace_text",
        "replace_text_in_file": "replace_text",
        "delete": "delete_file",
        "remove_file": "delete_file",
    }
    return aliases.get(operation, operation)


def _is_safe_project_path(path: str) -> bool:
    if not path or path.startswith("/") or path.startswith("\\"):
        return False
    if ":" in path or ".." in path.replace("\\", "/").split("/"):
        return False
    return True
