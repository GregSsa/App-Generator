"""LangGraph supervisor for the multi-agent Android generator."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .agents import (
    architect_agent,
    build_config_developer_agent,
    data_developer_agent,
    fix_agent,
    integration_developer_agent,
    product_manager_agent,
    ui_developer_agent,
    ui_agent,
    validator_agent,
)
from .android_project import write_project
from .state import AppGeneratorState


def route_after_validation(state: AppGeneratorState) -> str:
    if state.get("validation_errors") and state.get("iteration", 0) < state.get("max_iterations", 2):
        return "fix"
    return "done"


def route_after_fix(state: AppGeneratorState) -> str:
    return state.get("developer_focus", "integration")


def build_graph() -> Any:
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:
        raise RuntimeError(
            "LangGraph is not installed. Run `pip install -e .` or `pip install langgraph`."
        ) from exc

    workflow = StateGraph(AppGeneratorState)
    workflow.add_node("product_manager", product_manager_agent)
    workflow.add_node("architect", architect_agent)
    workflow.add_node("ui", ui_agent)
    workflow.add_node("build_config_developer", build_config_developer_agent)
    workflow.add_node("data_developer", data_developer_agent)
    workflow.add_node("ui_developer", ui_developer_agent)
    workflow.add_node("integration_developer", integration_developer_agent)
    workflow.add_node("validator", validator_agent)
    workflow.add_node("fix", fix_agent)

    workflow.add_edge(START, "product_manager")
    workflow.add_edge("product_manager", "architect")
    workflow.add_edge("architect", "ui")
    workflow.add_edge("ui", "build_config_developer")
    workflow.add_edge("build_config_developer", "data_developer")
    workflow.add_edge("data_developer", "ui_developer")
    workflow.add_edge("ui_developer", "integration_developer")
    workflow.add_edge("integration_developer", "validator")
    workflow.add_conditional_edges("validator", route_after_validation, {"fix": "fix", "done": END})
    workflow.add_conditional_edges(
        "fix",
        route_after_fix,
        {
            "build_config": "build_config_developer",
            "data": "data_developer",
            "ui": "ui_developer",
            "integration": "integration_developer",
        },
    )

    return workflow.compile()


def run_sequential_workflow(
    prompt: str,
    max_iterations: int = 2,
    use_openai: bool = True,
) -> AppGeneratorState:
    state: AppGeneratorState = {
        "prompt": prompt,
        "use_openai": use_openai,
        "iteration": 0,
        "max_iterations": max_iterations,
        "messages": [],
        "status": "draft",
    }

    focused_developer_sequences = {
        "build_config": (build_config_developer_agent, data_developer_agent, ui_developer_agent, integration_developer_agent),
        "data": (data_developer_agent, ui_developer_agent, integration_developer_agent),
        "ui": (ui_developer_agent, integration_developer_agent),
        "integration": (integration_developer_agent,),
    }

    for node in (
        product_manager_agent,
        architect_agent,
        ui_agent,
        build_config_developer_agent,
        data_developer_agent,
        ui_developer_agent,
        integration_developer_agent,
        validator_agent,
    ):
        state.update(node(state))

    while route_after_validation(state) == "fix":
        state.update(fix_agent(state))
        focus = route_after_fix(state)
        for node in focused_developer_sequences.get(focus, (integration_developer_agent,)):
            state.update(node(state))
        state.update(validator_agent(state))

    return state

def generate_application(
    prompt: str,
    max_iterations: int = 2,
    use_langgraph: bool = True,
    use_openai: bool = True,
    verbose: bool = False,
) -> AppGeneratorState:
    if not use_langgraph:
        return run_sequential_workflow(prompt=prompt, max_iterations=max_iterations, use_openai=use_openai)

    initial_state: AppGeneratorState = {
        "prompt": prompt,
        "use_openai": use_openai,
        "iteration": 0,
        "max_iterations": max_iterations,
        "messages": [],
        "status": "draft",
    }
    graph = build_graph()
    config = {"recursion_limit": max(25, 10 + max_iterations * 8)}
    if not verbose:
        return graph.invoke(initial_state, config=config)

    current_state: AppGeneratorState = initial_state
    for update in graph.stream(initial_state, config=config, stream_mode="updates"):
        for node_name, node_update in update.items():
            print(f"[graph] {node_name} completed")
            if isinstance(node_update, dict):
                current_state.update(node_update)
    return current_state


def generate_and_write(
    prompt: str,
    output_dir: Path,
    max_iterations: int = 2,
    use_langgraph: bool = True,
    use_openai: bool = True,
    verbose: bool = False,
) -> AppGeneratorState:
    final_state = generate_application(
        prompt=prompt,
        max_iterations=max_iterations,
        use_langgraph=use_langgraph,
        use_openai=use_openai,
        verbose=verbose,
    )
    if final_state.get("status") == "failed":
        return final_state
    write_project(final_state["files"], output_dir)
    return final_state
