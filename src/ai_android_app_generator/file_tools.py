"""Safe in-memory patch helpers for generated project files."""

from __future__ import annotations

from typing import Any

MAX_PATCHES = 20


def list_project_files(project_files: dict[str, str]) -> list[str]:
    return sorted(project_files.keys())


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
        operation = str(patch.get("op", "")).strip()
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


def _is_safe_project_path(path: str) -> bool:
    if not path or path.startswith("/") or path.startswith("\\"):
        return False
    if ":" in path or ".." in path.replace("\\", "/").split("/"):
        return False
    return True
