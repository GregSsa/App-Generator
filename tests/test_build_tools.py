from ai_android_app_generator.build_tools import parse_gradle_errors, run_android_build


def test_parse_gradle_errors_extracts_common_failures() -> None:
    output = """
    Execution failed for task ':app:compileDebugKotlin'.
    e: file:///tmp/MainActivity.kt:12: Unresolved reference 'Broken'
    """

    errors = parse_gradle_errors(output)

    assert len(errors) == 2
    assert "compileDebugKotlin" in errors[0]["message"]
    assert errors[1]["file"].endswith("MainActivity.kt")


def test_run_android_build_skips_when_gradle_is_missing(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("ai_android_app_generator.build_tools.shutil.which", lambda name: None)

    result = run_android_build({"settings.gradle.kts": 'rootProject.name = "Demo"'}, tmp_path)

    assert result["status"] == "skipped"
    assert result["warnings"][0]["file"] == "build"
