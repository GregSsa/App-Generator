"""Android build execution helpers."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from .android_project import write_project
from .state import ValidationIssue

MAX_BUILD_OUTPUT_CHARS = 16_000


def run_android_build(
    files: dict[str, str],
    output_dir: Path,
) -> dict[str, Any]:
    """Write the generated project and run a Gradle debug build when possible."""

    output_dir = output_dir.resolve()
    write_project(files, output_dir)

    command = _find_gradle_command(output_dir)
    if command is None:
        return {
            "status": "skipped",
            "command": None,
            "exit_code": None,
            "output": "",
            "errors": [],
            "warnings": [
                {
                    "severity": "warning",
                    "file": "build",
                    "message": "No Gradle wrapper or gradle executable was found; Android build was skipped.",
                }
            ],
        }

    completed = subprocess.run(
        command,
        cwd=output_dir,
        capture_output=True,
        text=True,
    )

    output = _trim_build_output((completed.stdout or "") + "\n" + (completed.stderr or ""))
    errors = parse_gradle_errors(output)
    if completed.returncode != 0 and not errors:
        errors = [
            {
                "severity": "error",
                "file": "build",
                "message": f"Gradle build failed with exit code {completed.returncode}.",
            }
        ]

    return {
        "status": "passed" if completed.returncode == 0 else "failed",
        "command": command,
        "exit_code": completed.returncode,
        "output": output,
        "errors": errors,
        "warnings": [],
    }


def parse_gradle_errors(output: str) -> list[ValidationIssue]:
    errors: list[ValidationIssue] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        lower = line.lower()
        if not line:
            continue
        if (
            line.startswith("e:")
            or "error:" in lower
            or "execution failed for task" in lower
            or "unresolved reference" in lower
            or "compilation error" in lower
            or "inconsistent jvm-target" in lower
        ):
            errors.append({"severity": "error", "file": _guess_file_from_error(line), "message": line[:500]})
            if len(errors) >= 10:
                break
    return errors


def _find_gradle_command(output_dir: Path) -> list[str] | None:
    gradlew_bat = output_dir / "gradlew.bat"
    if gradlew_bat.exists():
        return ["cmd", "/c", str(gradlew_bat), "assembleDebug", "--console=plain"]

    gradlew = output_dir / "gradlew"
    if gradlew.exists():
        return [str(gradlew), "assembleDebug", "--console=plain"]

    gradle = shutil.which("gradle")
    if gradle:
        return [gradle, "assembleDebug", "--console=plain"]

    return None


def _guess_file_from_error(message: str) -> str:
    for token in message.replace("\\", "/").split():
        cleaned = token.removeprefix("file://").strip(":")
        for extension in (".kt", ".kts", ".xml", ".java"):
            marker = f"{extension}:"
            if marker in cleaned:
                return cleaned.split(marker, 1)[0] + extension
            if cleaned.endswith(extension):
                return cleaned
    return "build"


def _trim_build_output(output: str) -> str:
    if len(output) <= MAX_BUILD_OUTPUT_CHARS:
        return output
    return output[-MAX_BUILD_OUTPUT_CHARS:]
