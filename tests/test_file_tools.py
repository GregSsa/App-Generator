from ai_android_app_generator.file_tools import apply_file_patches


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


def test_apply_file_patches_rejects_unsafe_paths() -> None:
    patched, results = apply_file_patches(
        {"safe.kt": "content"},
        [{"op": "upsert_file", "path": "../outside.kt", "content": "bad"}],
    )

    assert patched == {"safe.kt": "content"}
    assert results[0]["ok"] is False
