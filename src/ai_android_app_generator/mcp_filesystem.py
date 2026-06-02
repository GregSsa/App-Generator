"""Filesystem MCP Server bridge for generated project file inspection."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

MAX_FILE_CHARS = 64_000
MAX_SEARCH_MATCHES = 20


class MCPFilesystemUnavailable(RuntimeError):
    """Raised when the Filesystem MCP Server cannot be used."""


def execute_mcp_file_tool_requests(
    project_files: dict[str, str],
    tool_requests: Any,
) -> list[dict[str, Any]]:
    """Execute generated-project file requests through a Filesystem MCP Server."""

    if not isinstance(tool_requests, list):
        return []

    with tempfile.TemporaryDirectory(prefix="ai-android-generator-mcp-") as temp_dir:
        root = Path(temp_dir).resolve()
        _write_project_snapshot(root, project_files)
        return asyncio.run(_execute_requests(root, tool_requests))


def _write_project_snapshot(root: Path, project_files: dict[str, str]) -> None:
    for relative_path, content in project_files.items():
        destination = (root / relative_path).resolve()
        if root not in destination.parents and destination != root:
            raise MCPFilesystemUnavailable(f"Unsafe project path: {relative_path}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")


async def _execute_requests(root: Path, tool_requests: list[Any]) -> list[dict[str, Any]]:
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError as exc:
        raise MCPFilesystemUnavailable("Install MCP support with `pip install -e .[mcp]`.") from exc

    command = os.getenv("AI_GENERATOR_MCP_FILESYSTEM_COMMAND", "npx")
    args = _server_args(root)
    if shutil.which(command) is None:
        raise MCPFilesystemUnavailable(f"Filesystem MCP command not found: {command}")

    server_params = StdioServerParameters(command=command, args=args)
    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            results: list[dict[str, Any]] = []
            for request in tool_requests:
                if not isinstance(request, dict):
                    continue
                tool_name = str(request.get("tool", "")).strip()
                if tool_name == "list_project_files":
                    results.append({"tool": tool_name, "files": await _list_files(session, root)})
                elif tool_name == "read_project_files":
                    results.append(
                        {
                            "tool": tool_name,
                            "files": await _read_files(session, root, request.get("paths", [])),
                        }
                    )
                elif tool_name == "search_project_files":
                    results.append(
                        {
                            "tool": tool_name,
                            "matches": await _search_file_contents(session, root, str(request.get("query", ""))),
                        }
                    )
                else:
                    results.append({"tool": tool_name or "unknown", "error": "Unsupported file tool."})
            return results


def _server_args(root: Path) -> list[str]:
    raw_args = os.getenv("AI_GENERATOR_MCP_FILESYSTEM_ARGS")
    if raw_args:
        try:
            values = json.loads(raw_args)
        except json.JSONDecodeError as exc:
            raise MCPFilesystemUnavailable("AI_GENERATOR_MCP_FILESYSTEM_ARGS must be a JSON array.") from exc
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise MCPFilesystemUnavailable("AI_GENERATOR_MCP_FILESYSTEM_ARGS must be a JSON array of strings.")
        return [value.replace("{root}", str(root)) for value in values]
    return ["-y", "@modelcontextprotocol/server-filesystem", str(root)]


async def _list_files(session: Any, root: Path) -> list[str]:
    result = await session.call_tool("directory_tree", {"path": str(root)})
    tree = json.loads(_result_text(result))
    return sorted(_file_paths_from_tree(tree))


async def _read_files(session: Any, root: Path, paths: Any) -> dict[str, str]:
    if not isinstance(paths, list):
        return {}

    selected: dict[str, str] = {}
    for path in paths:
        if not isinstance(path, str):
            continue
        absolute_path = _safe_absolute_path(root, path)
        if absolute_path is None or not absolute_path.is_file():
            continue
        result = await session.call_tool("read_file", {"path": str(absolute_path)})
        selected[path] = _result_text(result)[:MAX_FILE_CHARS]
    return selected


async def _search_file_contents(session: Any, root: Path, query: str) -> list[dict[str, Any]]:
    query = query.strip()
    if not query:
        return []

    matches: list[dict[str, Any]] = []
    lowered_query = query.lower()
    for path in await _list_files(session, root):
        content = (await _read_files(session, root, [path])).get(path, "")
        for line_number, line in enumerate(content.splitlines(), start=1):
            if lowered_query in line.lower():
                matches.append({"file": path, "line": line_number, "text": line[:240]})
                if len(matches) >= MAX_SEARCH_MATCHES:
                    return matches
    return matches


def _safe_absolute_path(root: Path, relative_path: str) -> Path | None:
    if not relative_path or relative_path.startswith("/") or relative_path.startswith("\\"):
        return None
    if ":" in relative_path or ".." in relative_path.replace("\\", "/").split("/"):
        return None
    absolute_path = (root / relative_path).resolve()
    if root not in absolute_path.parents and absolute_path != root:
        return None
    return absolute_path


def _result_text(result: Any) -> str:
    content = getattr(result, "content", [])
    text_parts: list[str] = []
    for item in content:
        text = getattr(item, "text", None)
        if isinstance(text, str):
            text_parts.append(text)
    return "".join(text_parts)


def _file_paths_from_tree(tree: Any, prefix: str = "") -> list[str]:
    files: list[str] = []
    if isinstance(tree, list):
        for item in tree:
            files.extend(_file_paths_from_tree(item, prefix))
        return files

    if not isinstance(tree, dict):
        return files

    name = str(tree.get("name", "")).strip()
    node_type = str(tree.get("type", "")).strip().lower()
    next_prefix = f"{prefix}/{name}" if prefix and name else name or prefix
    if node_type == "file" and next_prefix:
        return [next_prefix]
    if node_type in {"directory", "folder"}:
        for child in tree.get("children", []):
            files.extend(_file_paths_from_tree(child, next_prefix))
    return files
