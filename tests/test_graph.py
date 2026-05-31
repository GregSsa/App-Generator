import pytest

from ai_android_app_generator.graph import generate_application, route_after_fix, route_after_validation, run_sequential_workflow


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


def test_fix_router_targets_focused_developer() -> None:
    route = route_after_fix({"prompt": "Demo", "developer_focus": "build_config"})

    assert route == "build_config"


def test_langgraph_workflow_generates_project_when_dependency_available() -> None:
    pytest.importorskip("langgraph")

    state = generate_application("Creer une application Android de suivi de mangas avec notifications", use_openai=False)

    assert state["status"] == "validated"
    assert state["app_name"] == "Manga Tracker"
    assert len(state["files"]) >= 10


def test_sequential_fallback_generates_project_without_langgraph() -> None:
    state = run_sequential_workflow("Creer une application Android de suivi de mangas avec notifications", use_openai=False)

    assert state["status"] == "validated"
    assert state["app_name"] == "Manga Tracker"
    assert len(state["files"]) >= 10
