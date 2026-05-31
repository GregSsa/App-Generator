"""Shared LangGraph state for the Android generator workflow."""

from __future__ import annotations

from typing import Any, Literal, TypedDict


class ValidationIssue(TypedDict):
    severity: Literal["error", "warning"]
    file: str
    message: str


class AppGeneratorState(TypedDict, total=False):
    prompt: str
    use_openai: bool
    app_name: str
    package_name: str
    app_profile: Literal["static_text", "data_driven"]
    requirements: list[str]
    architecture: dict[str, Any]
    screens: list[dict[str, Any]]
    data_models: list[dict[str, Any]]
    build_config_plan: dict[str, Any]
    data_plan: dict[str, Any]
    ui_implementation_plan: dict[str, Any]
    files: dict[str, str]
    patch_results: list[dict[str, Any]]
    validation_errors: list[ValidationIssue]
    validation_warnings: list[ValidationIssue]
    implementation_plan: dict[str, Any]
    fix_plan: dict[str, Any]
    developer_focus: Literal["build_config", "data", "ui", "integration"]
    iteration: int
    max_iterations: int
    status: Literal["draft", "generated", "needs_fix", "validated", "failed"]
    messages: list[str]
