"""Workflow agents for the Android generator."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .android_project import AndroidProjectBuilder, to_package_segment, to_pascal_case
from . import llm
from .build_tools import run_android_build
from .file_tools import apply_file_patches
from .state import AppGeneratorState

ANDROID_TOOLBOX = [
    {
        "name": "Material 3 + Compose adaptive",
        "use_when": "Every Compose UI; adaptive layouts when the app needs tablet/foldable/large-screen support.",
        "avoid_when": "Never avoid Material 3 for Compose UI, but avoid adaptive-only APIs for a single simple screen.",
    },
    {
        "name": "Navigation Compose / Navigation 3",
        "use_when": "The app has multiple screens, deep links, detail pages, or back-stack behavior.",
        "avoid_when": "A static single-screen app or simple list with no navigation.",
    },
    {
        "name": "Room",
        "use_when": "The app needs structured local persistence, offline-first data, relational queries, or cache tables.",
        "avoid_when": "Static content, temporary in-memory samples, or simple preferences.",
    },
    {
        "name": "DataStore",
        "use_when": "The app needs settings, user preferences, feature toggles, or small key-value persisted state.",
        "avoid_when": "Large relational app data or one-off static screens.",
    },
    {
        "name": "WorkManager",
        "use_when": "The app needs reliable background sync, periodic checks, notifications, or deferred work.",
        "avoid_when": "Foreground-only behavior or purely static UI.",
    },
    {
        "name": "Retrofit/Ktor",
        "use_when": "The app needs HTTP APIs, remote sync, feeds, search, authentication, or backend integration.",
        "avoid_when": "Local-only apps. Prefer one networking stack, not both.",
    },
    {
        "name": "Coil",
        "use_when": "The app displays remote/local images such as covers, avatars, posters, photos, or thumbnails.",
        "avoid_when": "Text-only UI.",
    },
]


def product_manager_agent(state: AppGeneratorState) -> dict[str, Any]:
    prompt = state["prompt"].strip()
    messages = state.get("messages", [])

    try:
        plan = llm.ask_openai_agent(
            "product_manager",
            (
                "You are the Product Manager agent for an Android app generator. "
                "Transform the user's idea into product requirements in French. "
                "Return JSON keys: app_name, app_profile, requirements. "
                "app_profile must be static_text for a simple static screen, otherwise data_driven. "
                "requirements must contain 3 to 8 strings. Do not omit required keys."
            ),
            {"prompt": prompt},
            project_files=state.get("files", {}),
        )
        app_name = require_non_empty_string(plan.get("app_name"), "product_manager.app_name")
        requirements = require_string_list(plan.get("requirements"), "product_manager.requirements", minimum=3)
        app_profile = require_app_profile(plan.get("app_profile"), "product_manager.app_profile")
        messages = messages + ["Product Manager: requirements generated with OpenAI."]
    except Exception as exc:
        return fail_agent("Product Manager", exc, messages)

    return {
        "app_name": app_name,
        "package_name": f"com.generated.{to_package_segment(app_name)}",
        "app_profile": app_profile,
        "requirements": requirements,
        "status": "draft",
        "messages": messages,
    }


def architect_agent(state: AppGeneratorState) -> dict[str, Any]:
    messages = state.get("messages", [])

    try:
        plan = llm.ask_openai_agent(
            "architect",
            (
                "You are the Android Architect agent. Design a practical Android architecture "
                "Optimize for the smallest architecture that fully satisfies the user's prompt. "
                "Prefer boring, compilable, maintainable Android patterns over clever abstractions. "
                "Use the provided android_toolbox to choose libraries deliberately. "
                "Do not select Room, DataStore, WorkManager, Navigation, networking, or Coil unless "
                "a requirement clearly needs it. "
                "for the provided requirements. Return JSON keys: architecture. architecture "
                "must match app_profile. For static_text apps, do not add ViewModel, Repository, "
                "Room, WorkManager, or dynamic data layers unless the prompt asks for state. "
                "Do not omit required keys."
            ),
            {
                "prompt": state["prompt"],
                "app_name": state.get("app_name"),
                "app_profile": state.get("app_profile"),
                "requirements": state.get("requirements", []),
            },
            project_files=state.get("files", {}),
        )
        architecture = require_dict(plan.get("architecture"), "architect.architecture")
        messages = messages + ["Architect: architecture generated with OpenAI."]
    except Exception as exc:
        return fail_agent("Architect", exc, messages)

    return {
        "architecture": architecture,
        "messages": messages,
    }


def ui_agent(state: AppGeneratorState) -> dict[str, Any]:
    app_profile = state.get("app_profile", "data_driven")
    messages = state.get("messages", [])

    try:
        plan = llm.ask_openai_agent(
            "ui",
            (
                "You are the Jetpack Compose UI agent. Produce screens and data models for "
                "a polished but minimal implementation. Keep the UI scope aligned with the prompt; "
                "do not invent extra screens, navigation, persistence, or settings unless needed. "
                "Use Material 3 by default, Compose adaptive for large-screen needs, Navigation "
                "only when there are multiple real destinations, and Coil only when images are needed. "
                "the Android app. Return JSON keys: screens, data_models. screens must be a "
                "list of objects with name, purpose, components. data_models must be a list "
                "of objects with name and fields, where fields have name and Kotlin type. "
                "For static_text apps, return an empty data_models list. For data_driven apps, "
                "return at least one model with fields that match the user's domain. "
                "Do not omit required keys."
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
        screens = require_list_of_dicts(plan.get("screens"), "ui.screens", minimum=1)
        raw_models = require_list(plan.get("data_models"), "ui.data_models")
        data_models = normalize_data_models(raw_models, state["prompt"], app_profile)
        messages = messages + ["UI Agent: screens and models generated with OpenAI."]
    except Exception as exc:
        return fail_agent("UI Agent", exc, messages)

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
            "Select optional libraries from the Android toolbox only when requirements justify them.",
        ],
        "dependencies": generated_dependencies_for_profile(state.get("app_profile", "data_driven"), state["prompt"]),
        "available_toolbox": ANDROID_TOOLBOX,
    }
    messages = state.get("messages", [])

    try:
        plan = llm.ask_openai_agent(
            "build_config_developer",
            (
                "You are the Android Build Config Developer. Produce only the Gradle/build "
                "implementation plan. Quality bar: compilation first, version compatibility, "
                "no unused dependencies, Java/Kotlin target alignment. Use the android_toolbox "
                "to decide whether Material 3 adaptive, Navigation Compose/Navigation 3, Room, "
                "DataStore, WorkManager, Retrofit/Ktor, or Coil are needed. Return JSON key "
                "build_config_plan. If you need concrete Gradle changes, include "
                "build_config_plan.file_patches. Each patch must use op exactly equal to "
                "upsert_file, replace_text, or delete_file. "
                "Do not describe files or snippets unless you also provide file_patches. "
                "Do not omit required keys."
            ),
            _developer_payload(state),
            project_files=state.get("files", {}),
        )
        build_config_plan = require_dict(plan.get("build_config_plan"), "build_config_developer.build_config_plan")
        messages = messages + ["Build Config Developer: build plan generated with OpenAI."]
    except Exception as exc:
        return fail_agent("Build Config Developer", exc, messages)

    return {"build_config_plan": build_config_plan, "messages": messages}


def data_developer_agent(state: AppGeneratorState) -> dict[str, Any]:
    app_profile = state.get("app_profile", "data_driven")
    data_plan = {
        "scope": "Models and repository layer.",
        "quality_bar": [
            "Generate no data layer for static_text.",
            "Keep models small and Kotlin-friendly.",
            "Avoid fake persistence unless the requirements ask for it.",
            "Use Room for structured local data; use DataStore only for small preferences.",
        ],
        "enabled": app_profile != "static_text",
        "models": state.get("data_models", []),
    }
    messages = state.get("messages", [])

    try:
        plan = llm.ask_openai_agent(
            "data_developer",
            (
                "You are the Android Data Developer. Plan only data models, repositories, "
                "and persistence boundaries. Quality bar: no unnecessary layers, no invented "
                "backends, simple Kotlin types, compile-ready interfaces. For static_text, "
                "return enabled=false. Use Room only for structured offline data, DataStore only "
                "for preferences, Retrofit/Ktor only for remote APIs, and WorkManager only for "
                "background sync or notifications. "
                "Return JSON key data_plan. If you create Kotlin data/repository code, include "
                "data_plan.file_patches. Each patch must use op exactly equal to "
                "upsert_file, replace_text, or delete_file. "
                "Do not describe files or snippets unless you also provide file_patches. "
                "Do not omit required keys."
            ),
            _developer_payload(state),
            project_files=state.get("files", {}),
        )
        data_plan = require_dict(plan.get("data_plan"), "data_developer.data_plan")
        messages = messages + ["Data Developer: data plan generated with OpenAI."]
    except Exception as exc:
        return fail_agent("Data Developer", exc, messages)

    return {"data_plan": data_plan, "messages": messages}


def ui_developer_agent(state: AppGeneratorState) -> dict[str, Any]:
    ui_implementation_plan = {
        "scope": "Jetpack Compose implementation.",
        "quality_bar": [
            "Use stable Compose APIs.",
            "Use Material 3 components by default.",
            "Use Compose adaptive only for large-screen/adaptive requirements.",
            "Use Navigation Compose/Navigation 3 only for multiple destinations.",
            "Use Coil only when the UI renders images.",
            "Keep composables small and readable.",
            "Avoid navigation/state machinery unless required.",
            "Make text visible, centered or scan-friendly depending on app_profile.",
        ],
        "screens": state.get("screens", []),
    }
    messages = state.get("messages", [])

    try:
        plan = llm.ask_openai_agent(
            "ui_developer",
            (
                "You are the Jetpack Compose Developer. Plan only UI implementation details. "
                "Quality bar: simple composables, no overlapping text, no unused state, compile-ready "
                "imports, appropriate layout for the prompt. Use Material 3 by default; use Compose "
                "adaptive, Navigation Compose/Navigation 3, and Coil only when requirements justify them. "
                "Return JSON key ui_implementation_plan. If you create or change Compose code, include "
                "ui_implementation_plan.file_patches. Each patch must use op exactly equal to "
                "upsert_file, replace_text, or delete_file "
                "with complete file contents for new files. Do not output file_map, snippets, or code "
                "descriptions unless those changes are materialized in file_patches. Do not omit required keys."
            ),
            _developer_payload(state),
            project_files=state.get("files", {}),
        )
        ui_implementation_plan = require_dict(plan.get("ui_implementation_plan"), "ui_developer.ui_implementation_plan")
        messages = messages + ["UI Developer: UI implementation plan generated with OpenAI."]
    except Exception as exc:
        return fail_agent("UI Developer", exc, messages)

    return {"ui_implementation_plan": ui_implementation_plan, "messages": messages}


def integration_developer_agent(state: AppGeneratorState) -> dict[str, Any]:
    implementation_plan = {
        "strategy": "Assemble a compact Kotlin/Compose project from specialist developer plans.",
        "generated_layers": generated_layers_for_profile(state.get("app_profile", "data_driven")),
        "quality_bar": [
            "Every generated Kotlin file must compile in isolation with its imports.",
            "Do not generate files contradicted by app_profile.",
            "Prefer fewer files when requirements are simple.",
            "Keep generated code stable and easy for QA to inspect.",
        ],
    }
    messages = state.get("messages", [])

    try:
        plan = llm.ask_openai_agent(
            "integration_developer",
            (
                "You are the Integration Developer. Assemble the outputs from Build Config, "
                "Data, and UI developers into one coherent Android project plan. Quality bar: "
                "compile-ready file graph, no duplicate responsibilities, no stale files, no "
                "architecture beyond the user need. Return JSON key implementation_plan. "
                "You must bridge plans to files: if any specialist plan describes concrete files, snippets, "
                "screens, routes, ViewModels, repositories, dependencies, or build settings that are not "
                "already represented in generated files, include implementation_plan.file_patches with "
                "structured patches. Each patch must use op exactly equal to replace_text, upsert_file, "
                "or delete_file. Do not leave promised "
                "code as prose only. Do not omit required keys."
            ),
            _developer_payload(state),
            project_files=state.get("files", {}),
        )
        implementation_plan = require_dict(plan.get("implementation_plan"), "integration_developer.implementation_plan")
        messages = messages + ["Integration Developer: assembly plan generated with OpenAI."]
    except Exception as exc:
        return fail_agent("Integration Developer", exc, messages)

    state_for_build = {**state, "implementation_plan": implementation_plan}
    files = AndroidProjectBuilder().build(state_for_build)
    unmaterialized_plans = _plans_with_unmaterialized_code(state, implementation_plan)
    if unmaterialized_plans:
        return fail_agent(
            "Integration Developer",
            ValueError(
                "specialist plans describe code but did not provide file_patches: "
                + ", ".join(unmaterialized_plans)
            ),
            messages,
        )
    files, patch_results = apply_file_patches(files, _collect_file_patches(state, implementation_plan))
    failed_patches = [result for result in patch_results if not result.get("ok")]
    if failed_patches:
        return fail_agent(
            "Integration Developer",
            ValueError(f"file_patches could not be applied: {failed_patches}"),
            messages,
        )
    return {
        "files": files,
        "implementation_plan": implementation_plan,
        "patch_results": patch_results,
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

    try:
        plan = llm.ask_openai_agent(
            "validator",
            (
                "You are the QA Validator agent. Review the generated Android project state "
                "for logic, architecture, and build risks. Return JSON keys: validation_errors, "
                "validation_warnings. Each issue must have severity, file, and message. "
                "Only report validation_errors for likely compile failures or broken requirements. "
                "Architecture preference issues must be validation_warnings. Be precise: name "
                "the owner area as build_config, data, ui, or integration when possible. "
                "Do not omit required keys; use empty lists when there are no issues."
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
                "static_errors": errors,
                "static_warnings": warnings,
            },
            project_files=state.get("files", {}),
        )
        require_list(plan.get("validation_errors"), "validator.validation_errors")
        require_list(plan.get("validation_warnings"), "validator.validation_warnings")
        openai_errors, openai_warnings = split_openai_issues(plan.get("validation_errors"))
        errors = errors + openai_errors
        warnings = warnings + openai_warnings
        warnings = warnings + normalize_issues(plan.get("validation_warnings"), "warning")
        messages = messages + ["QA: validation reviewed with OpenAI."]
    except Exception as exc:
        return fail_agent("QA Validator", exc, messages)

    status = "needs_fix" if errors else "validated"
    return {
        "validation_errors": errors,
        "validation_warnings": warnings,
        "status": status,
        "messages": messages + [f"QA: validation completed with {len(errors)} error(s) and {len(warnings)} warning(s)."],
    }


def build_agent(state: AppGeneratorState) -> dict[str, Any]:
    messages = state.get("messages", [])
    output_dir = state.get("output_dir")
    if not output_dir:
        return {
            "build_result": {"status": "skipped", "reason": "No output_dir configured for build agent."},
            "build_errors": [],
            "build_warnings": [],
            "status": state.get("status", "validated"),
            "messages": messages + ["Build Agent: skipped because no output directory was configured."],
        }

    build_result = run_android_build(
        state.get("files", {}),
        Path(output_dir),
    )
    build_errors = build_result.get("errors", [])
    build_warnings = build_result.get("warnings", [])
    status = "needs_fix" if build_errors else state.get("status", "validated")

    validation_errors = state.get("validation_errors", [])
    validation_warnings = state.get("validation_warnings", [])
    if build_errors:
        validation_errors = validation_errors + build_errors
    if build_warnings:
        validation_warnings = validation_warnings + build_warnings

    return {
        "build_result": build_result,
        "build_errors": build_errors,
        "build_warnings": build_warnings,
        "validation_errors": validation_errors,
        "validation_warnings": validation_warnings,
        "status": status,
        "messages": messages + [f"Build Agent: build {build_result['status']}."],
    }


def fix_agent(state: AppGeneratorState) -> dict[str, Any]:
    next_iteration = state.get("iteration", 0) + 1
    fix_plan = {
        "strategy": "Regenerate project files from the latest validated state.",
        "errors_seen": state.get("validation_errors", []),
        "build_result": state.get("build_result", {}),
        "developer_focus": infer_developer_focus(state.get("validation_errors", [])),
    }
    messages = state.get("messages", [])

    try:
        plan = llm.ask_openai_agent(
            "fix",
            (
                "You are the Fix agent. Propose corrections for validation errors in the "
                "generated Android project, including real Gradle build errors when present. "
                "Do not rewrite everything. Identify the smallest "
                "specialist developer that should revisit the work: build_config, data, ui, or "
                "integration. Return JSON key fix_plan with summary, developer_focus, and actions. "
                "Do not omit required keys."
            ),
            {
                "prompt": state["prompt"],
                "requirements": state.get("requirements", []),
                "architecture": state.get("architecture", {}),
                "validation_errors": state.get("validation_errors", []),
                "validation_warnings": state.get("validation_warnings", []),
                "build_result": state.get("build_result", {}),
                "iteration": next_iteration,
            },
            project_files=state.get("files", {}),
        )
        fix_plan = require_dict(plan.get("fix_plan"), "fix.fix_plan")
        messages = messages + ["Fix Agent: correction plan generated with OpenAI."]
    except Exception as exc:
        return fail_agent("Fix Agent", exc, messages)

    developer_focus = require_developer_focus(fix_plan.get("developer_focus"), "fix.fix_plan.developer_focus")
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


def fail_agent(agent_name: str, exc: Exception, messages: list[str]) -> dict[str, Any]:
    message = f"{agent_name}: generation aborted because OpenAI failed ({exc})."
    issue = {"severity": "error", "file": "openai", "message": message}
    return {
        "status": "failed",
        "generation_errors": [issue],
        "validation_errors": [issue],
        "messages": messages + [message],
    }


def default_architecture(app_profile: str = "data_driven") -> dict[str, Any]:
    if app_profile == "static_text":
        return {
            "pattern": "Single Activity",
            "ui": "Jetpack Compose + Material 3",
            "state": "No ViewModel for static content",
        "data": [],
        "background": [],
        "toolbox": ["Material 3"],
        "quality": ["Unit test for generated prompt intent", "Static validation before export"],
        }

    return {
        "pattern": "MVVM",
        "ui": "Jetpack Compose + Material 3",
        "state": "StateFlow exposed by ViewModel",
        "data": ["Repository", "Room-ready data models"],
        "background": ["WorkManager-ready notification workflow"],
        "toolbox": ["Material 3", "Navigation when multiple screens", "Room/DataStore/WorkManager/Retrofit/Ktor/Coil when required"],
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


def generated_dependencies_for_profile(app_profile: str, prompt: str = "") -> list[str]:
    dependencies = [
        "androidx.activity:activity-compose",
        "androidx.compose.material3:material3",
        "androidx.compose.ui:ui",
    ]
    lower = prompt.lower()
    if app_profile != "static_text":
        dependencies.extend(
            [
                "androidx.lifecycle:lifecycle-viewmodel-compose",
                "org.jetbrains.kotlinx:kotlinx-coroutines-android",
            ]
        )
    if any(marker in lower for marker in ["navigation", "detail", "details", "ecran detail", "plusieurs ecrans"]):
        dependencies.append("Navigation Compose / Navigation 3")
    if any(marker in lower for marker in ["offline", "hors ligne", "database", "base de donnees", "room"]):
        dependencies.append("Room")
    if any(marker in lower for marker in ["settings", "preferences", "parametres", "datastore"]):
        dependencies.append("DataStore")
    if any(marker in lower for marker in ["notification", "background", "sync", "periodic", "workmanager"]):
        dependencies.append("WorkManager")
    if any(marker in lower for marker in ["api", "http", "remote", "serveur", "backend", "retrofit", "ktor"]):
        dependencies.append("Retrofit or Ktor")
    if any(marker in lower for marker in ["image", "cover", "avatar", "photo", "poster", "thumbnail", "couverture"]):
        dependencies.append("Coil")
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
        "android_toolbox": ANDROID_TOOLBOX,
        "quality_instruction": (
            "Generate less code, but better code. Respect app_profile, avoid unused layers, "
            "and prefer code that is obvious, compile-ready, and easy to validate. Use Material 3 "
            "by default and select Compose adaptive, Navigation, Room, DataStore, WorkManager, "
            "Retrofit/Ktor, and Coil only when the prompt requires them."
        ),
    }


def _collect_file_patches(state: AppGeneratorState, implementation_plan: dict[str, Any]) -> list[dict[str, Any]]:
    patches: list[dict[str, Any]] = []
    for plan_key in ("build_config_plan", "data_plan", "ui_implementation_plan"):
        patches.extend(_safe_patch_list(state.get(plan_key, {}).get("file_patches")))
    patches.extend(_safe_patch_list(implementation_plan.get("file_patches")))
    return patches


def _plans_with_unmaterialized_code(
    state: AppGeneratorState,
    implementation_plan: dict[str, Any],
) -> list[str]:
    integration_has_patches = bool(_safe_patch_list(implementation_plan.get("file_patches")))
    missing: list[str] = []
    for plan_key in ("build_config_plan", "data_plan", "ui_implementation_plan"):
        plan = state.get(plan_key, {})
        if not isinstance(plan, dict):
            continue
        if _safe_patch_list(plan.get("file_patches")):
            continue
        if integration_has_patches:
            continue
        if _contains_unmaterialized_code_intent(plan):
            missing.append(plan_key)
    return missing


def _safe_patch_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _contains_unmaterialized_code_intent(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized_key = str(key).lower()
            if normalized_key in {"file_map", "snippet", "snippets", "kotlin_files", "source_files"}:
                return True
            if _contains_unmaterialized_code_intent(child):
                return True
    elif isinstance(value, list):
        return any(_contains_unmaterialized_code_intent(item) for item in value)
    return False


def normalize_data_models(models: list[dict[str, Any]], prompt: str, app_profile: str = "data_driven") -> list[dict[str, Any]]:
    if app_profile == "static_text":
        return []

    if not models:
        raise ValueError("ui.data_models must contain at least one model for data_driven apps")

    normalized: list[dict[str, Any]] = []
    for model in models:
        name = to_pascal_case(require_non_empty_string(model.get("name"), "ui.data_models[].name"))
        fields = require_list_of_dicts(model.get("fields"), "ui.data_models[].fields", minimum=1)
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

        if not normalized_fields:
            raise ValueError("ui.data_models[].fields must contain at least one valid field")

        normalized.append({"name": name, "fields": normalized_fields})

    return normalized


def normalize_issues(value: Any, severity: str) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    issue_items = value if isinstance(value, list) else []
    for issue in [item for item in issue_items if isinstance(item, dict)]:
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


def require_non_empty_string(value: Any, field_name: str) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


def require_app_profile(value: Any, field_name: str) -> str:
    text = str(value).strip()
    if text not in {"static_text", "data_driven"}:
        raise ValueError(f"{field_name} must be static_text or data_driven")
    return text


def require_developer_focus(value: Any, field_name: str) -> str:
    text = str(value).strip()
    if text not in {"build_config", "data", "ui", "integration"}:
        raise ValueError(f"{field_name} must be build_config, data, ui, or integration")
    return text


def require_list(value: Any, field_name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    return value


def require_string_list(value: Any, field_name: str, minimum: int = 1) -> list[str]:
    items = require_list(value, field_name)
    strings = [str(item).strip() for item in items if str(item).strip()]
    if len(strings) < minimum:
        raise ValueError(f"{field_name} must contain at least {minimum} non-empty strings")
    return strings


def require_list_of_dicts(value: Any, field_name: str, minimum: int = 0) -> list[dict[str, Any]]:
    items = require_list(value, field_name)
    dicts = [item for item in items if isinstance(item, dict)]
    if len(dicts) < minimum or len(dicts) != len(items):
        raise ValueError(f"{field_name} must contain dictionaries only")
    return dicts


def require_dict(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        raise ValueError(f"{field_name} must be a non-empty object")
    return value


def _safe_kotlin_type(value: str) -> str:
    allowed = {"String", "Int", "Long", "Float", "Double", "Boolean"}
    cleaned = value.strip().replace("?", "")
    return cleaned if cleaned in allowed else "String"
