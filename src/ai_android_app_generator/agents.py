"""Workflow agents for the Android generator."""

from __future__ import annotations

import re
from typing import Any

from .android_project import AndroidProjectBuilder, to_package_segment, to_pascal_case
from . import llm
from .state import AppGeneratorState


def product_manager_agent(state: AppGeneratorState) -> dict[str, Any]:
    prompt = state["prompt"].strip()
    messages = state.get("messages", [])

    if state.get("use_openai"):
        try:
            plan = llm.ask_openai_agent(
                "product_manager",
                (
                    "You are the Product Manager agent for an Android app generator. "
                    "Transform the user's idea into product requirements in French. "
                    "Return JSON keys: app_name, app_profile, requirements. "
                    "app_profile must be static_text for a simple static screen, otherwise data_driven. "
                    "requirements must contain 3 to 8 strings."
                ),
                {"prompt": prompt},
                project_files=state.get("files", {}),
            )
            app_name = _as_non_empty_string(plan.get("app_name"), infer_app_name(prompt))
            requirements = _as_string_list(plan.get("requirements"), infer_requirements(prompt), minimum=3)
            app_profile = _as_app_profile(plan.get("app_profile"), infer_app_profile(prompt))
            messages = messages + ["Product Manager: requirements generated with OpenAI."]
        except Exception as exc:
            app_name = infer_app_name(prompt)
            requirements = infer_requirements(prompt)
            app_profile = infer_app_profile(prompt)
            messages = messages + [f"Product Manager: OpenAI unavailable, used local fallback ({exc})."]
    else:
        app_name = infer_app_name(prompt)
        requirements = infer_requirements(prompt)
        app_profile = infer_app_profile(prompt)
        messages = messages + ["Product Manager: requirements generated."]

    return {
        "app_name": app_name,
        "package_name": f"com.generated.{to_package_segment(app_name)}",
        "app_profile": app_profile,
        "requirements": requirements,
        "status": "draft",
        "messages": messages,
    }


def architect_agent(state: AppGeneratorState) -> dict[str, Any]:
    architecture = default_architecture(state.get("app_profile", "data_driven"))
    messages = state.get("messages", [])

    if state.get("use_openai"):
        try:
            plan = llm.ask_openai_agent(
                "architect",
                (
                    "You are the Android Architect agent. Design a practical Android architecture "
                    "Optimize for the smallest architecture that fully satisfies the user's prompt. "
                    "Prefer boring, compilable, maintainable Android patterns over clever abstractions. "
                    "for the provided requirements. Return JSON keys: architecture. architecture "
                    "must match app_profile. For static_text apps, do not add ViewModel, Repository, "
                    "Room, WorkManager, or dynamic data layers unless the prompt asks for state."
                ),
                {
                    "prompt": state["prompt"],
                    "app_name": state.get("app_name"),
                    "app_profile": state.get("app_profile"),
                    "requirements": state.get("requirements", []),
                },
                project_files=state.get("files", {}),
            )
            architecture = _as_dict(plan.get("architecture"), architecture)
            messages = messages + ["Architect: architecture generated with OpenAI."]
        except Exception as exc:
            messages = messages + [f"Architect: OpenAI unavailable, used local fallback ({exc})."]
    else:
        messages = messages + [f"Architect: {architecture['pattern']} Compose architecture selected."]

    return {
        "architecture": architecture,
        "messages": messages,
    }


def ui_agent(state: AppGeneratorState) -> dict[str, Any]:
    app_profile = state.get("app_profile", "data_driven")
    screens = default_screens(app_profile)
    data_models = default_data_models(state["prompt"], app_profile)
    messages = state.get("messages", [])

    if state.get("use_openai"):
        try:
            plan = llm.ask_openai_agent(
                "ui",
                (
                    "You are the Jetpack Compose UI agent. Produce screens and data models for "
                    "a polished but minimal implementation. Keep the UI scope aligned with the prompt; "
                    "do not invent extra screens, navigation, persistence, or settings unless needed. "
                    "the Android app. Return JSON keys: screens, data_models. screens must be a "
                    "list of objects with name, purpose, components. data_models must be a list "
                    "of objects with name and fields, where fields have name and Kotlin type. "
                    "For static_text apps, return an empty data_models list."
                ),
                {
                    "prompt": state["prompt"],
                    "app_name": state.get("app_name"),
                    "app_profile": app_profile,
                    "requirements": state.get("requirements", []),
                    "architecture": state.get("architecture", {}),
                },
                project_files=state.get("files", {}),
            )
            screens = _as_list_of_dicts(plan.get("screens"), screens)
            raw_models = plan.get("data_models")
            data_models = normalize_data_models(raw_models if isinstance(raw_models, list) else data_models, state["prompt"], app_profile)
            messages = messages + ["UI Agent: screens and models generated with OpenAI."]
        except Exception as exc:
            messages = messages + [f"UI Agent: OpenAI unavailable, used local fallback ({exc})."]
    else:
        messages = messages + ["UI Agent: Compose screens specified."]

    return {
        "screens": screens,
        "data_models": data_models,
        "messages": messages,
    }


def build_config_developer_agent(state: AppGeneratorState) -> dict[str, Any]:
    build_config_plan = {
        "scope": "Gradle Android application configuration.",
        "quality_bar": [
            "Use compatible Android Gradle, Kotlin, and Compose plugin versions.",
            "Align Java and Kotlin compilation with jvmToolchain(17).",
            "Include only dependencies required by app_profile.",
        ],
        "dependencies": generated_dependencies_for_profile(state.get("app_profile", "data_driven")),
    }
    messages = state.get("messages", [])

    if state.get("use_openai"):
        try:
            plan = llm.ask_openai_agent(
                "build_config_developer",
                (
                    "You are the Android Build Config Developer. Produce only the Gradle/build "
                    "implementation plan. Quality bar: compilation first, version compatibility, "
                    "no unused dependencies, Java/Kotlin target alignment. Return JSON key "
                    "build_config_plan."
                ),
                _developer_payload(state),
                project_files=state.get("files", {}),
            )
            build_config_plan = _as_dict(plan.get("build_config_plan"), build_config_plan)
            messages = messages + ["Build Config Developer: build plan generated with OpenAI."]
        except Exception as exc:
            messages = messages + [f"Build Config Developer: OpenAI unavailable, used local plan ({exc})."]
    else:
        messages = messages + ["Build Config Developer: Gradle plan generated."]

    return {"build_config_plan": build_config_plan, "messages": messages}


def data_developer_agent(state: AppGeneratorState) -> dict[str, Any]:
    app_profile = state.get("app_profile", "data_driven")
    data_plan = {
        "scope": "Models and repository layer.",
        "quality_bar": [
            "Generate no data layer for static_text.",
            "Keep models small and Kotlin-friendly.",
            "Avoid fake persistence unless the requirements ask for it.",
        ],
        "enabled": app_profile != "static_text",
        "models": state.get("data_models", []),
    }
    messages = state.get("messages", [])

    if state.get("use_openai"):
        try:
            plan = llm.ask_openai_agent(
                "data_developer",
                (
                    "You are the Android Data Developer. Plan only data models, repositories, "
                    "and persistence boundaries. Quality bar: no unnecessary layers, no invented "
                    "backends, simple Kotlin types, compile-ready interfaces. For static_text, "
                    "return enabled=false. Return JSON key data_plan."
                ),
                _developer_payload(state),
                project_files=state.get("files", {}),
            )
            data_plan = _as_dict(plan.get("data_plan"), data_plan)
            messages = messages + ["Data Developer: data plan generated with OpenAI."]
        except Exception as exc:
            messages = messages + [f"Data Developer: OpenAI unavailable, used local plan ({exc})."]
    else:
        messages = messages + ["Data Developer: data plan generated."]

    return {"data_plan": data_plan, "messages": messages}


def ui_developer_agent(state: AppGeneratorState) -> dict[str, Any]:
    ui_implementation_plan = {
        "scope": "Jetpack Compose implementation.",
        "quality_bar": [
            "Use stable Compose APIs.",
            "Keep composables small and readable.",
            "Avoid navigation/state machinery unless required.",
            "Make text visible, centered or scan-friendly depending on app_profile.",
        ],
        "screens": state.get("screens", []),
    }
    messages = state.get("messages", [])

    if state.get("use_openai"):
        try:
            plan = llm.ask_openai_agent(
                "ui_developer",
                (
                    "You are the Jetpack Compose Developer. Plan only UI implementation details. "
                    "Quality bar: simple composables, no overlapping text, no unused state, compile-ready "
                    "imports, appropriate layout for the prompt. Return JSON key ui_implementation_plan."
                ),
                _developer_payload(state),
                project_files=state.get("files", {}),
            )
            ui_implementation_plan = _as_dict(plan.get("ui_implementation_plan"), ui_implementation_plan)
            messages = messages + ["UI Developer: UI implementation plan generated with OpenAI."]
        except Exception as exc:
            messages = messages + [f"UI Developer: OpenAI unavailable, used local plan ({exc})."]
    else:
        messages = messages + ["UI Developer: UI implementation plan generated."]

    return {"ui_implementation_plan": ui_implementation_plan, "messages": messages}


def integration_developer_agent(state: AppGeneratorState) -> dict[str, Any]:
    implementation_plan = {
        "strategy": "Assemble a compact Kotlin/Compose project from specialist developer plans.",
        "generated_layers": generated_layers_for_profile(state.get("app_profile", "data_driven")),
        "quality_bar": [
            "Every generated Kotlin file must compile in isolation with its imports.",
            "Do not generate files contradicted by app_profile.",
            "Prefer fewer files when requirements are simple.",
            "Keep generated code deterministic and easy for QA to inspect.",
        ],
    }
    messages = state.get("messages", [])

    if state.get("use_openai"):
        try:
            plan = llm.ask_openai_agent(
                "integration_developer",
                (
                    "You are the Integration Developer. Assemble the outputs from Build Config, "
                    "Data, and UI developers into one coherent Android project plan. Quality bar: "
                    "compile-ready file graph, no duplicate responsibilities, no stale files, no "
                    "architecture beyond the user need. Return JSON key implementation_plan."
                ),
                _developer_payload(state),
                project_files=state.get("files", {}),
            )
            implementation_plan = _as_dict(plan.get("implementation_plan"), implementation_plan)
            messages = messages + ["Integration Developer: assembly plan generated with OpenAI."]
        except Exception as exc:
            messages = messages + [f"Integration Developer: OpenAI unavailable, used local assembly plan ({exc})."]
    else:
        messages = messages + ["Integration Developer: assembly plan generated."]

    state_for_build = {**state, "implementation_plan": implementation_plan}
    files = AndroidProjectBuilder().build(state_for_build)
    return {
        "files": files,
        "implementation_plan": implementation_plan,
        "status": "generated",
        "messages": messages + [f"Integration Developer: generated {len(files)} project files."],
    }


def developer_agent(state: AppGeneratorState) -> dict[str, Any]:
    """Backward-compatible wrapper for callers that still expect one developer."""

    state.update(build_config_developer_agent(state))
    state.update(data_developer_agent(state))
    state.update(ui_developer_agent(state))
    return integration_developer_agent(state)


def validator_agent(state: AppGeneratorState) -> dict[str, Any]:
    errors, warnings = AndroidProjectBuilder().validate(state.get("files", {}), state)
    messages = state.get("messages", [])

    if state.get("use_openai"):
        try:
            plan = llm.ask_openai_agent(
                "validator",
                (
                    "You are the QA Validator agent. Review the generated Android project state "
                    "for logic, architecture, and build risks. Return JSON keys: validation_errors, "
                    "validation_warnings. Each issue must have severity, file, and message. "
                    "Only report validation_errors for likely compile failures or broken requirements. "
                    "Architecture preference issues must be validation_warnings. Be precise: name "
                    "the owner area as build_config, data, ui, or integration when possible."
                ),
                {
                    "prompt": state["prompt"],
                    "app_profile": state.get("app_profile"),
                    "requirements": state.get("requirements", []),
                    "architecture": state.get("architecture", {}),
                    "screens": state.get("screens", []),
                    "build_config_plan": state.get("build_config_plan", {}),
                    "data_plan": state.get("data_plan", {}),
                    "ui_implementation_plan": state.get("ui_implementation_plan", {}),
                    "implementation_plan": state.get("implementation_plan", {}),
                    "files": sorted(state.get("files", {}).keys()),
                    "deterministic_errors": errors,
                    "deterministic_warnings": warnings,
                },
                project_files=state.get("files", {}),
            )
            openai_errors, openai_warnings = split_openai_issues(plan.get("validation_errors"))
            errors = errors + openai_errors
            warnings = warnings + openai_warnings
            warnings = warnings + normalize_issues(plan.get("validation_warnings"), "warning")
            messages = messages + ["QA: validation reviewed with OpenAI."]
        except Exception as exc:
            messages = messages + [f"QA: OpenAI unavailable, used static validation only ({exc})."]

    status = "needs_fix" if errors else "validated"
    return {
        "validation_errors": errors,
        "validation_warnings": warnings,
        "status": status,
        "messages": messages + [f"QA: validation completed with {len(errors)} error(s) and {len(warnings)} warning(s)."],
    }


def fix_agent(state: AppGeneratorState) -> dict[str, Any]:
    next_iteration = state.get("iteration", 0) + 1
    fix_plan = {
        "strategy": "Regenerate project files from the latest validated state.",
        "errors_seen": state.get("validation_errors", []),
        "developer_focus": infer_developer_focus(state.get("validation_errors", [])),
    }
    messages = state.get("messages", [])

    if state.get("use_openai"):
        try:
            plan = llm.ask_openai_agent(
                "fix",
                (
                    "You are the Fix agent. Propose corrections for validation errors in the "
                    "generated Android project. Do not rewrite everything. Identify the smallest "
                    "specialist developer that should revisit the work: build_config, data, ui, or "
                    "integration. Return JSON key fix_plan with summary, developer_focus, and actions."
                ),
                {
                    "prompt": state["prompt"],
                    "requirements": state.get("requirements", []),
                    "architecture": state.get("architecture", {}),
                    "validation_errors": state.get("validation_errors", []),
                    "validation_warnings": state.get("validation_warnings", []),
                    "iteration": next_iteration,
                },
                project_files=state.get("files", {}),
            )
            fix_plan = _as_dict(plan.get("fix_plan"), fix_plan)
            messages = messages + ["Fix Agent: correction plan generated with OpenAI."]
        except Exception as exc:
            messages = messages + [f"Fix Agent: OpenAI unavailable, used local correction plan ({exc})."]

    developer_focus = _as_developer_focus(
        fix_plan.get("developer_focus"),
        infer_developer_focus(state.get("validation_errors", [])),
    )
    fix_plan = {**fix_plan, "developer_focus": developer_focus}
    state_for_build = {**state, "fix_plan": fix_plan}
    fixed_files = AndroidProjectBuilder().build(state_for_build)
    return {
        "files": fixed_files,
        "fix_plan": fix_plan,
        "developer_focus": developer_focus,
        "iteration": next_iteration,
        "status": "generated",
        "messages": messages + [f"Fix Agent: regenerated project files, attempt {next_iteration}."],
    }


def default_architecture(app_profile: str = "data_driven") -> dict[str, Any]:
    if app_profile == "static_text":
        return {
            "pattern": "Single Activity",
            "ui": "Jetpack Compose + Material 3",
            "state": "No ViewModel for static content",
            "data": [],
            "background": [],
            "quality": ["Unit test for generated prompt intent", "Static validation before export"],
        }

    return {
        "pattern": "MVVM",
        "ui": "Jetpack Compose + Material 3",
        "state": "StateFlow exposed by ViewModel",
        "data": ["Repository", "Room-ready data models"],
        "background": ["WorkManager-ready notification workflow"],
        "quality": ["Unit tests for generated requirements", "Static validation before export"],
    }


def default_screens(app_profile: str = "data_driven") -> list[dict[str, Any]]:
    if app_profile == "static_text":
        return [
            {
                "name": "Hello",
                "purpose": "Display a polished static message.",
                "components": ["Centered text", "Material theme"],
            }
        ]

    return [
        {
            "name": "Home",
            "purpose": "Overview of tracked content and high-priority updates.",
            "components": ["Header", "Notification toggle", "Requirement chips", "Tracked item list"],
        },
        {
            "name": "Detail",
            "purpose": "Focused view for a tracked item.",
            "components": ["Title", "Status", "Latest update", "Primary action"],
        },
        {
            "name": "Settings",
            "purpose": "Notification and sync preferences.",
            "components": ["Notification switch", "Sync cadence", "Account placeholder"],
        },
    ]


def default_data_models(prompt: str, app_profile: str = "data_driven") -> list[dict[str, Any]]:
    if app_profile == "static_text":
        return []

    return [
        {
            "name": infer_model_name(prompt),
            "fields": [
                {"name": "title", "type": "String"},
                {"name": "subtitle", "type": "String"},
                {"name": "status", "type": "String"},
            ],
        }
    ]


def infer_app_name(prompt: str) -> str:
    lower = prompt.lower()
    if "hello world" in lower or "hello" in lower:
        return "Hello World"
    if "manga" in lower:
        return "Manga Tracker"
    if "budget" in lower or "finance" in lower:
        return "Budget Companion"
    if "fitness" in lower or "sport" in lower:
        return "Fitness Tracker"
    if "todo" in lower or "tache" in lower or "task" in lower:
        return "Task Planner"

    words = re.findall(r"[A-Za-zÀ-ÿ0-9]+", prompt)
    useful_words = [word for word in words if len(word) > 3][:3]
    return " ".join(useful_words) if useful_words else "Generated Android App"


def infer_model_name(prompt: str) -> str:
    lower = prompt.lower()
    if "manga" in lower:
        return "Manga"
    if "budget" in lower or "finance" in lower:
        return "BudgetEntry"
    if "fitness" in lower or "sport" in lower:
        return "Workout"
    if "todo" in lower or "tache" in lower or "task" in lower:
        return "TaskItem"
    return f"{to_pascal_case(infer_app_name(prompt))}Item"


def infer_requirements(prompt: str) -> list[str]:
    lower = prompt.lower()
    if infer_app_profile(prompt) == "static_text":
        return [
            "Afficher le texte demande de maniere claire.",
            "Utiliser une interface Jetpack Compose simple et propre.",
            "Eviter les couches techniques inutiles pour une app statique.",
        ]

    requirements = [
        "Afficher un tableau de bord clair pour les donnees principales.",
        "Permettre a l'utilisateur d'ajouter, consulter et suivre des elements.",
        "Conserver une architecture testable et evolutive.",
    ]

    if "manga" in lower:
        requirements.extend(
            [
                "Suivre une liste de mangas favoris.",
                "Afficher le dernier chapitre disponible pour chaque manga.",
                "Notifier l'utilisateur lorsqu'un nouveau chapitre est detecte.",
            ]
        )

    if "notification" in lower or "notifier" in lower:
        requirements.append("Permettre d'activer ou desactiver les notifications.")

    if "offline" in lower or "hors ligne" in lower:
        requirements.append("Rendre les donnees principales disponibles hors ligne.")

    return list(dict.fromkeys(requirements))


def infer_app_profile(prompt: str) -> str:
    lower = prompt.lower()
    static_markers = ["hello world", "affiche", "afficher", "texte statique", "static text"]
    dynamic_markers = ["tracker", "suivi", "liste", "notification", "base de donnees", "chapitre", "favoris"]
    if any(marker in lower for marker in static_markers) and not any(marker in lower for marker in dynamic_markers):
        return "static_text"
    return "data_driven"


def generated_layers_for_profile(app_profile: str) -> list[str]:
    if app_profile == "static_text":
        return ["activity", "compose_ui", "unit_test"]
    return ["activity", "ui", "viewmodel", "repository", "models", "unit_test"]


def generated_dependencies_for_profile(app_profile: str) -> list[str]:
    dependencies = [
        "androidx.activity:activity-compose",
        "androidx.compose.material3:material3",
        "androidx.compose.ui:ui",
    ]
    if app_profile != "static_text":
        dependencies.extend(
            [
                "androidx.lifecycle:lifecycle-viewmodel-compose",
                "org.jetbrains.kotlinx:kotlinx-coroutines-android",
            ]
        )
    return dependencies


def infer_developer_focus(errors: list[dict[str, Any]]) -> str:
    haystack = " ".join(f"{issue.get('file', '')} {issue.get('message', '')}" for issue in errors).lower()
    if "gradle" in haystack or "jvm" in haystack or "manifest" in haystack:
        return "build_config"
    if "/data/" in haystack or "repository" in haystack or "model" in haystack:
        return "data"
    if "/ui/" in haystack or "compose" in haystack or "layout" in haystack or "text" in haystack:
        return "ui"
    return "integration"


def _developer_payload(state: AppGeneratorState) -> dict[str, Any]:
    return {
        "prompt": state["prompt"],
        "app_name": state.get("app_name"),
        "package_name": state.get("package_name"),
        "app_profile": state.get("app_profile"),
        "requirements": state.get("requirements", []),
        "architecture": state.get("architecture", {}),
        "screens": state.get("screens", []),
        "data_models": state.get("data_models", []),
        "build_config_plan": state.get("build_config_plan", {}),
        "data_plan": state.get("data_plan", {}),
        "ui_implementation_plan": state.get("ui_implementation_plan", {}),
        "validation_errors": state.get("validation_errors", []),
        "validation_warnings": state.get("validation_warnings", []),
        "quality_instruction": (
            "Generate less code, but better code. Respect app_profile, avoid unused layers, "
            "and prefer code that is obvious, compile-ready, and easy to validate."
        ),
    }


def normalize_data_models(models: list[dict[str, Any]], prompt: str, app_profile: str = "data_driven") -> list[dict[str, Any]]:
    if app_profile == "static_text":
        return []

    if not models:
        return default_data_models(prompt, app_profile)

    normalized: list[dict[str, Any]] = []
    for model in models:
        name = to_pascal_case(str(model.get("name", ""))) or infer_model_name(prompt)
        fields = _as_list_of_dicts(model.get("fields"), [])
        normalized_fields = []
        for field in fields:
            field_name = re.sub(r"[^A-Za-z0-9_]", "", str(field.get("name", "")))
            if not field_name:
                continue
            if field_name[0].isdigit():
                field_name = f"field{field_name}"
            normalized_fields.append(
                {
                    "name": field_name[:1].lower() + field_name[1:],
                    "type": _safe_kotlin_type(str(field.get("type", "String"))),
                }
            )

        existing_names = {field["name"] for field in normalized_fields}
        for required_field in default_data_models(prompt, app_profile)[0]["fields"]:
            if required_field["name"] not in existing_names:
                normalized_fields.append(required_field)

        normalized.append({"name": name, "fields": normalized_fields})

    return normalized


def normalize_issues(value: Any, severity: str) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    for issue in _as_list_of_dicts(value, []):
        message = str(issue.get("message", "")).strip()
        if not message:
            continue
        issues.append(
            {
                "severity": severity,
                "file": str(issue.get("file", "generated-project")).strip() or "generated-project",
                "message": message,
            }
        )
    return issues


def split_openai_issues(value: Any) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    for issue in normalize_issues(value, "error"):
        if _is_hard_validation_error(issue["message"]):
            errors.append(issue)
        else:
            issue["severity"] = "warning"
            warnings.append(issue)
    return errors, warnings


def _is_hard_validation_error(message: str) -> bool:
    lower = message.lower()
    hard_markers = [
        "compile",
        "compilation",
        "unresolved",
        "missing required",
        "crash",
        "does not initialize",
        "syntax",
        "type mismatch",
        "jvm-target",
        "jvm target",
    ]
    soft_markers = ["unnecessary", "redundant", "not needed", "prefer", "should"]
    if any(marker in lower for marker in hard_markers):
        return True
    if any(marker in lower for marker in soft_markers):
        return False
    return True


def _as_app_profile(value: Any, fallback: str) -> str:
    text = str(value).strip()
    if text in {"static_text", "data_driven"}:
        return text
    return fallback


def _as_developer_focus(value: Any, fallback: str) -> str:
    text = str(value).strip()
    if text in {"build_config", "data", "ui", "integration"}:
        return text
    return fallback


def _safe_kotlin_type(value: str) -> str:
    allowed = {"String", "Int", "Long", "Float", "Double", "Boolean"}
    cleaned = value.strip().replace("?", "")
    return cleaned if cleaned in allowed else "String"


def _as_non_empty_string(value: Any, fallback: str) -> str:
    text = str(value).strip() if value is not None else ""
    return text or fallback


def _as_string_list(value: Any, fallback: list[str], minimum: int = 1) -> list[str]:
    if not isinstance(value, list):
        return fallback
    strings = [str(item).strip() for item in value if str(item).strip()]
    return strings if len(strings) >= minimum else fallback


def _as_list_of_dicts(value: Any, fallback: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return fallback
    dicts = [item for item in value if isinstance(item, dict)]
    return dicts or fallback


def _as_dict(value: Any, fallback: dict[str, Any]) -> dict[str, Any]:
    return value if isinstance(value, dict) and value else fallback
