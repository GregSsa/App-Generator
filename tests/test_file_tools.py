from ai_android_app_generator.file_tools import apply_file_patches, execute_file_tool_requests


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


def test_apply_file_patches_replaces_text() -> None:
    files = {"app/src/main/java/MainActivity.kt": 'Text("Hello")'}

    patched, results = apply_file_patches(
        files,
        [
            {
                "op": "replace_text",
                "path": "app/src/main/java/MainActivity.kt",
                "old": 'Text("Hello")',
                "new": 'Text("Hello World")',
            }
        ],
    )

    assert patched["app/src/main/java/MainActivity.kt"] == 'Text("Hello World")'
    assert results == [{"op": "replace_text", "path": "app/src/main/java/MainActivity.kt", "ok": True}]


def test_apply_file_patches_accepts_common_operation_aliases() -> None:
    patched, results = apply_file_patches(
        {},
        [
            {
                "operation": "create_file",
                "path": "settings.gradle.kts",
                "content": 'rootProject.name = "Demo"\n',
            }
        ],
    )

    assert patched["settings.gradle.kts"] == 'rootProject.name = "Demo"\n'
    assert results == [{"op": "upsert_file", "path": "settings.gradle.kts", "ok": True}]


def test_apply_file_patches_rejects_unsafe_paths() -> None:
    patched, results = apply_file_patches(
        {"safe.kt": "content"},
        [{"op": "upsert_file", "path": "../outside.kt", "content": "bad"}],
    )

    assert patched == {"safe.kt": "content"}
    assert results[0]["ok"] is False
