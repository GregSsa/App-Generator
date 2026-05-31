from ai_android_app_generator.agents import (
    ANDROID_TOOLBOX,
    architect_agent,
    build_config_developer_agent,
    data_developer_agent,
    developer_agent,
    fix_agent,
    integration_developer_agent,
    product_manager_agent,
    ui_developer_agent,
    ui_agent,
    validator_agent,
    generated_dependencies_for_profile,
)
from ai_android_app_generator.graph import run_sequential_workflow


def fake_openai_agent(agent_name: str, system_prompt: str, payload: dict, project_files=None) -> dict:
    responses = {
        "product_manager": {
            "app_name": "Manga Tracker",
            "app_profile": "data_driven",
            "requirements": [
                "Suivre une liste de mangas favoris.",
                "Afficher le dernier chapitre disponible.",
                "Envoyer une notification lors des nouveaux chapitres.",
            ],
        },
        "architect": {
            "architecture": {
                "pattern": "MVVM",
                "ui": "Jetpack Compose + Material 3",
                "state": "StateFlow exposed by ViewModel",
                "data": ["Repository"],
                "background": ["WorkManager"],
                "quality": ["Unit tests"],
            }
        },
        "ui": {
            "screens": [
                {
                    "name": "Home",
                    "purpose": "Track manga updates.",
                    "components": ["Header", "List", "Notification toggle"],
                }
            ],
            "data_models": [
                {
                    "name": "Manga",
                    "fields": [
                        {"name": "title", "type": "String"},
                        {"name": "subtitle", "type": "String"},
                        {"name": "status", "type": "String"},
                    ],
                }
            ],
        },
        "build_config_developer": {"build_config_plan": {"dependencies": ["compose"]}},
        "data_developer": {"data_plan": {"enabled": True, "models": ["Manga"]}},
        "ui_developer": {"ui_implementation_plan": {"screens": ["Home"]}},
        "integration_developer": {"implementation_plan": {"kotlin_files": ["MainActivity.kt"]}},
        "validator": {"validation_errors": [], "validation_warnings": []},
        "fix": {
            "fix_plan": {
                "summary": "Regenerate files after validation errors.",
                "developer_focus": "integration",
                "actions": ["rebuild"],
            }
        },
    }
    return responses[agent_name]


def fake_static_openai_agent(agent_name: str, system_prompt: str, payload: dict, project_files=None) -> dict:
    responses = fake_openai_agent(agent_name, system_prompt, payload, project_files)
    if agent_name == "product_manager":
        return {
            "app_name": "Hello World",
            "app_profile": "static_text",
            "requirements": [
                "Afficher le texte Hello World clairement.",
                "Utiliser une interface Jetpack Compose simple.",
                "Eviter les couches techniques inutiles.",
            ],
        }
    if agent_name == "architect":
        return {"architecture": {"pattern": "Single Activity", "ui": "Jetpack Compose + Material 3", "state": "No ViewModel"}}
    if agent_name == "ui":
        return {
            "screens": [{"name": "Hello", "purpose": "Display Hello World.", "components": ["Centered text"]}],
            "data_models": [],
        }
    if agent_name == "data_developer":
        return {"data_plan": {"enabled": False, "models": []}}
    return responses


def test_product_manager_uses_openai_requirements(monkeypatch) -> None:
    monkeypatch.setattr("ai_android_app_generator.llm.ask_openai_agent", fake_openai_agent)

    state = product_manager_agent({"prompt": "Creer une application Android de suivi de mangas avec notifications"})

    assert state["app_name"] == "Manga Tracker"
    assert state["package_name"] == "com.generated.mangatracker"
    assert any("mangas" in requirement for requirement in state["requirements"])
    assert any("notification" in requirement.lower() for requirement in state["requirements"])


def test_generation_produces_valid_android_project_files(monkeypatch) -> None:
    monkeypatch.setattr("ai_android_app_generator.llm.ask_openai_agent", fake_openai_agent)

    state = {"prompt": "Tracker de mangas avec notifications", "messages": [], "iteration": 0, "max_iterations": 2}
    state.update(product_manager_agent(state))
    state.update(architect_agent(state))
    state.update(ui_agent(state))
    state.update(developer_agent(state))
    state.update(validator_agent(state))

    files = state["files"]
    assert state["status"] == "validated"
    assert state["validation_errors"] == []
    assert "settings.gradle.kts" in files
    assert "app/build.gradle.kts" in files
    assert "app/src/main/res/values/styles.xml" in files
    assert "setContent" in files["app/src/main/java/com/generated/mangatracker/MainActivity.kt"]
    assert "LazyColumn" in files["app/src/main/java/com/generated/mangatracker/ui/AppScreens.kt"]
    assert "jvmToolchain(17)" in files["app/build.gradle.kts"]


def test_static_prompt_generates_minimal_compose_project(monkeypatch) -> None:
    monkeypatch.setattr("ai_android_app_generator.llm.ask_openai_agent", fake_static_openai_agent)

    state = run_sequential_workflow(
        "Creer une application Android qui affiche proprement Hello World",
    )

    files = state["files"]
    main_activity = files["app/src/main/java/com/generated/helloworld/MainActivity.kt"]

    assert state["status"] == "validated"
    assert state["app_profile"] == "static_text"
    assert "Hello World" in main_activity
    assert "viewModels" not in main_activity
    assert "app/src/main/java/com/generated/helloworld/data/AppModels.kt" not in files
    assert "app/src/main/java/com/generated/helloworld/data/AppRepository.kt" not in files
    assert "app/src/main/java/com/generated/helloworld/ui/AppViewModel.kt" not in files
    assert "sourceCompatibility = JavaVersion.VERSION_17" in files["app/build.gradle.kts"]
    assert "jvmToolchain(17)" in files["app/build.gradle.kts"]


def test_openai_mode_calls_each_main_agent(monkeypatch) -> None:
    calls: list[str] = []

    def tracked_openai_agent(agent_name: str, system_prompt: str, payload: dict, project_files=None) -> dict:
        calls.append(agent_name)
        return fake_openai_agent(agent_name, system_prompt, payload, project_files)

    monkeypatch.setattr("ai_android_app_generator.llm.ask_openai_agent", tracked_openai_agent)

    state = run_sequential_workflow(
        "Creer une application Android de suivi de mangas avec notifications",
    )

    assert state["status"] == "validated"
    assert calls == [
        "product_manager",
        "architect",
        "ui",
        "build_config_developer",
        "data_developer",
        "ui_developer",
        "integration_developer",
        "validator",
    ]


def test_specialized_developers_create_separate_plans(monkeypatch) -> None:
    monkeypatch.setattr("ai_android_app_generator.llm.ask_openai_agent", fake_openai_agent)

    state = {"prompt": "Tracker de mangas avec notifications", "messages": [], "iteration": 0, "max_iterations": 2}
    state.update(product_manager_agent(state))
    state.update(architect_agent(state))
    state.update(ui_agent(state))
    state.update(build_config_developer_agent(state))
    state.update(data_developer_agent(state))
    state.update(ui_developer_agent(state))
    state.update(integration_developer_agent(state))

    assert "build_config_plan" in state
    assert "data_plan" in state
    assert "ui_implementation_plan" in state
    assert "implementation_plan" in state
    assert "files" in state


def test_android_toolbox_guides_optional_dependencies() -> None:
    dependencies = generated_dependencies_for_profile(
        "data_driven",
        "tracker de mangas offline avec notifications, images de couverture et API distante",
    )

    assert "androidx.compose.material3:material3" in dependencies
    assert "Room" in dependencies
    assert "WorkManager" in dependencies
    assert "Retrofit or Ktor" in dependencies
    assert "Coil" in dependencies
    assert any(tool["name"] == "Material 3 + Compose adaptive" for tool in ANDROID_TOOLBOX)


def test_integration_developer_applies_targeted_file_patches(monkeypatch) -> None:
    def fake_openai_agent(agent_name: str, system_prompt: str, payload: dict, project_files=None) -> dict:
        if agent_name == "integration_developer":
            return {
                "implementation_plan": {
                    "file_patches": [
                        {
                            "op": "replace_text",
                            "path": "app/src/main/java/com/generated/helloworld/MainActivity.kt",
                            "old": "Hello World",
                            "new": "Bonjour Android",
                        }
                    ]
                }
            }
        return {"agent": agent_name}

    monkeypatch.setattr("ai_android_app_generator.llm.ask_openai_agent", fake_openai_agent)

    monkeypatch.setattr("ai_android_app_generator.llm.ask_openai_agent", fake_static_openai_agent)
    state = run_sequential_workflow("Creer une application Android qui affiche proprement Hello World")
    monkeypatch.setattr("ai_android_app_generator.llm.ask_openai_agent", fake_openai_agent)
    result = integration_developer_agent(state)

    main_activity = result["files"]["app/src/main/java/com/generated/helloworld/MainActivity.kt"]
    assert "Bonjour Android" in main_activity
    assert result["patch_results"][0]["ok"] is True


def test_specialist_file_patches_are_materialized(monkeypatch) -> None:
    def patching_openai_agent(agent_name: str, system_prompt: str, payload: dict, project_files=None) -> dict:
        if agent_name == "ui_developer":
            return {
                "ui_implementation_plan": {
                    "file_patches": [
                        {
                            "op": "upsert_file",
                            "path": "app/src/main/java/com/generated/mangatracker/ui/ExtraScreen.kt",
                            "content": "package com.generated.mangatracker.ui\n\nfun extraScreenMarker() = \"ok\"\n",
                        }
                    ]
                }
            }
        return fake_openai_agent(agent_name, system_prompt, payload, project_files)

    monkeypatch.setattr("ai_android_app_generator.llm.ask_openai_agent", patching_openai_agent)

    state = run_sequential_workflow("Creer une application Android de suivi de mangas avec notifications")

    assert state["status"] == "validated"
    assert "app/src/main/java/com/generated/mangatracker/ui/ExtraScreen.kt" in state["files"]


def test_integration_fails_when_specialist_describes_code_without_patches(monkeypatch) -> None:
    def prose_only_openai_agent(agent_name: str, system_prompt: str, payload: dict, project_files=None) -> dict:
        if agent_name == "ui_developer":
            return {
                "ui_implementation_plan": {
                    "file_map": ["ui/list/MangaListScreen.kt"],
                    "screens": [{"name": "MangaListScreen", "snippet": "@Composable fun MangaListScreen() {}"}],
                }
            }
        if agent_name == "integration_developer":
            return {"implementation_plan": {"summary": "No concrete patches."}}
        return fake_openai_agent(agent_name, system_prompt, payload, project_files)

    monkeypatch.setattr("ai_android_app_generator.llm.ask_openai_agent", prose_only_openai_agent)

    state = run_sequential_workflow("Creer une application Android de suivi de mangas avec notifications")

    assert state["status"] == "failed"
    assert "ui_implementation_plan" in state["generation_errors"][0]["message"]


def test_openai_mode_calls_fix_agent(monkeypatch) -> None:
    calls: list[str] = []

    def fake_openai_agent(agent_name: str, system_prompt: str, payload: dict, project_files=None) -> dict:
        calls.append(agent_name)
        return {
            "fix_plan": {
                "summary": "Regenerate files after validation errors.",
                "developer_focus": "integration",
                "actions": ["rebuild"],
            }
        }

    monkeypatch.setattr("ai_android_app_generator.llm.ask_openai_agent", fake_openai_agent)

    state = {
        "prompt": "Demo",
        "app_name": "Demo",
        "package_name": "com.generated.demo",
        "requirements": ["Requirement A", "Requirement B", "Requirement C"],
        "architecture": {},
        "screens": [],
        "data_models": [{"name": "DemoItem", "fields": [{"name": "title", "type": "String"}]}],
        "validation_errors": [{"severity": "error", "file": "MainActivity.kt", "message": "Broken"}],
        "messages": [],
        "iteration": 0,
        "max_iterations": 2,
    }

    result = fix_agent(state)

    assert calls == ["fix"]
    assert result["fix_plan"]["summary"] == "Regenerate files after validation errors."


def test_openai_failure_aborts_instead_of_using_template(monkeypatch) -> None:
    def broken_openai_agent(agent_name: str, system_prompt: str, payload: dict, project_files=None) -> dict:
        raise RuntimeError("bad api key")

    monkeypatch.setattr("ai_android_app_generator.llm.ask_openai_agent", broken_openai_agent)

    result = product_manager_agent(
        {
            "prompt": "Creer une application Android de suivi de mangas avec notifications",
            "messages": [],
        }
    )

    assert result["status"] == "failed"
    assert "app_name" not in result
    assert "bad api key" in result["generation_errors"][0]["message"]
