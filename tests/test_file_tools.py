from ai_android_app_generator.file_tools import execute_file_tool_requests


def test_file_tools_read_only_requested_files() -> None:
    files = {
        "app/build.gradle.kts": "kotlin { jvmToolchain(17) }",
        "app/src/main/java/MainActivity.kt": "class MainActivity",
    }

    results = execute_file_tool_requests(
        files,
        [{"tool": "read_project_files", "paths": ["app/build.gradle.kts", "missing.kt"]}],
    )

    assert results == [
        {
            "tool": "read_project_files",
            "files": {"app/build.gradle.kts": "kotlin { jvmToolchain(17) }"},
        }
    ]


def test_file_tools_search_project_files() -> None:
    files = {
        "app/build.gradle.kts": "kotlin { jvmToolchain(17) }",
        "README.md": "No match here",
    }

    results = execute_file_tool_requests(files, [{"tool": "search_project_files", "query": "jvmToolchain"}])

    assert results[0]["matches"] == [
        {"file": "app/build.gradle.kts", "line": 1, "text": "kotlin { jvmToolchain(17) }"}
    ]
