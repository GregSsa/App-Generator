import pytest

from ai_android_app_generator.graph import (
    generate_application,
    route_after_build,
    route_after_fix,
    route_after_validation,
    run_sequential_workflow,
)
from tests.test_agents import fake_openai_agent


def test_validation_router_requests_fix_when_errors_remain() -> None:
    route = route_after_validation(
        {
            "prompt": "Demo",
            "iteration": 0,
            "max_iterations": 2,
            "validation_errors": [{"severity": "error", "file": "x", "message": "broken"}],
        }
    )

    assert route == "fix"


def test_validation_router_finishes_after_iteration_budget() -> None:
    route = route_after_validation(
        {
            "prompt": "Demo",
            "iteration": 2,
            "max_iterations": 2,
            "validation_errors": [{"severity": "error", "file": "x", "message": "broken"}],
        }
    )

    assert route == "done"


def test_validation_router_builds_when_static_validation_passes() -> None:
    route = route_after_validation({"prompt": "Demo", "validation_errors": []})

    assert route == "build"


def test_build_router_requests_fix_when_build_fails() -> None:
    route = route_after_build(
        {
            "prompt": "Demo",
            "iteration": 0,
            "max_iterations": 2,
            "build_errors": [{"severity": "error", "file": "build", "message": "compile failed"}],
        }
    )

    assert route == "fix"


def test_fix_router_targets_focused_developer() -> None:
    route = route_after_fix({"prompt": "Demo", "developer_focus": "build_config"})

    assert route == "build_config"


def test_langgraph_workflow_generates_project_when_dependency_available(monkeypatch) -> None:
    pytest.importorskip("langgraph")
    monkeypatch.setattr("ai_android_app_generator.llm.ask_openai_agent", fake_openai_agent)

    state = generate_application("Creer une application Android de suivi de mangas avec notifications")

    assert state["status"] == "validated"
    assert state["app_name"] == "Manga Tracker"
    assert len(state["files"]) >= 10


def test_sequential_workflow_generates_project_without_langgraph(monkeypatch) -> None:
    monkeypatch.setattr("ai_android_app_generator.llm.ask_openai_agent", fake_openai_agent)

    state = run_sequential_workflow("Creer une application Android de suivi de mangas avec notifications")

    assert state["status"] == "validated"
    assert state["app_name"] == "Manga Tracker"
    assert len(state["files"]) >= 10


def test_openai_failure_stops_workflow_without_files(monkeypatch) -> None:
    def broken_openai_agent(agent_name: str, system_prompt: str, payload: dict, project_files=None) -> dict:
        raise RuntimeError("bad api key")

    monkeypatch.setattr("ai_android_app_generator.llm.ask_openai_agent", broken_openai_agent)

    state = run_sequential_workflow("Creer une application Android de suivi de mangas avec notifications")

    assert state["status"] == "failed"
    assert "files" not in state
    assert state["generation_errors"][0]["file"] == "openai"
