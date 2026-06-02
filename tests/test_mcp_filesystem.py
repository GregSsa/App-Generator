from pathlib import Path

from ai_android_app_generator.mcp_filesystem import (
    _file_paths_from_tree,
    _safe_absolute_path,
    _server_args,
    execute_mcp_file_tool_requests,
)


def test_mcp_file_tools_ignore_missing_requests() -> None:
    assert execute_mcp_file_tool_requests({"README.md": "demo"}, None) == []


def test_mcp_filesystem_server_args_default_to_official_server() -> None:
    args = _server_args(Path("C:/tmp/project"))

    assert args[:2] == ["-y", "@modelcontextprotocol/server-filesystem"]
    assert args[-1].endswith("project")


def test_mcp_filesystem_rejects_unsafe_paths(tmp_path) -> None:
    assert _safe_absolute_path(tmp_path, "../outside.kt") is None
    assert _safe_absolute_path(tmp_path, "C:/outside.kt") is None
    assert _safe_absolute_path(tmp_path, "app/build.gradle.kts") == (tmp_path / "app/build.gradle.kts").resolve()


def test_mcp_filesystem_extracts_files_from_directory_tree() -> None:
    tree = [
        {"name": "settings.gradle.kts", "type": "file"},
        {
            "name": "app",
            "type": "directory",
            "children": [{"name": "build.gradle.kts", "type": "file"}],
        },
    ]

    assert _file_paths_from_tree(tree) == ["settings.gradle.kts", "app/build.gradle.kts"]
