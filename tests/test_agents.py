from ai_android_app_generator.agents import (
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
)
from ai_android_app_generator.graph import run_sequential_workflow


def test_product_manager_infers_manga_requirements() -> None:
    state = product_manager_agent({"prompt": "Creer une application Android de suivi de mangas avec notifications"})

    assert state["app_name"] == "Manga Tracker"
    assert state["package_name"] == "com.generated.mangatracker"
    assert any("mangas" in requirement for requirement in state["requirements"])
    assert any("notifications" in requirement for requirement in state["requirements"])


def test_generation_produces_valid_android_project_files() -> None:
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


def test_static_prompt_generates_minimal_compose_project() -> None:
    state = run_sequential_workflow(
        "Creer une application Android qui affiche proprement Hello World",
        use_openai=False,
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

    def fake_openai_agent(agent_name: str, system_prompt: str, payload: dict, project_files=None) -> dict:
        calls.append(agent_name)
        responses = {
            "product_manager": {
                "app_name": "Manga Tracker",
                "requirements": [
                    "Suivre une liste de mangas favoris.",
                    "Afficher le dernier chapitre disponible.",
                    "Notifier l'utilisateur des nouveaux chapitres.",
                ],
            },
            "architect": {
                "architecture": {
                    "pattern": "MVVM",
                    "ui": "Jetpack Compose",
                    "state": "StateFlow",
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
        }
        return responses[agent_name]

    monkeypatch.setattr("ai_android_app_generator.llm.ask_openai_agent", fake_openai_agent)

    state = run_sequential_workflow(
        "Creer une application Android de suivi de mangas avec notifications",
        use_openai=True,
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


def test_specialized_developers_create_separate_plans() -> None:
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


def test_openai_mode_calls_fix_agent(monkeypatch) -> None:
    calls: list[str] = []

    def fake_openai_agent(agent_name: str, system_prompt: str, payload: dict, project_files=None) -> dict:
        calls.append(agent_name)
        return {"fix_plan": {"summary": "Regenerate files after validation errors.", "actions": ["rebuild"]}}

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
        "use_openai": True,
    }

    result = fix_agent(state)

    assert calls == ["fix"]
    assert result["fix_plan"]["summary"] == "Regenerate files after validation errors."
