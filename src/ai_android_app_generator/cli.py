"""Command line interface."""

from __future__ import annotations

from pathlib import Path

import typer
from dotenv import load_dotenv

load_dotenv(override=True)

from .android_project import to_package_segment
from .graph import generate_and_write

app = typer.Typer(help="Generate Android Kotlin/Compose projects with a LangGraph multi-agent workflow.")


@app.command()
def generate(
    prompt: str = typer.Argument(..., help="Application idea, e.g. 'Tracker de mangas avec notifications'."),
    output: Path | None = typer.Option(None, "--output", "-o", help="Directory where the Android project is written."),
    max_iterations: int = typer.Option(2, "--max-iterations", min=0, help="Maximum QA/fix loop attempts."),
    sequential: bool = typer.Option(False, "--sequential", help="Run without LangGraph for local dry runs."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Print each completed LangGraph node."),
) -> None:
    """Generate and export an Android project."""

    import os

    if verbose:
        os.environ["AI_GENERATOR_VERBOSE"] = "1"
    target = output or Path("generated") / to_package_segment(prompt[:48])
    state = generate_and_write(
        prompt=prompt,
        output_dir=target,
        max_iterations=max_iterations,
        use_langgraph=not sequential,
        verbose=verbose,
    )

    if state.get("status") == "failed":
        typer.echo("Status: failed")
        for issue in state.get("generation_errors", state.get("validation_errors", [])):
            typer.echo(f"ERROR {issue['file']}: {issue['message']}")
        raise typer.Exit(code=1)

    typer.echo(f"Application: {state['app_name']}")
    typer.echo(f"Package: {state['package_name']}")
    typer.echo(f"Status: {state['status']}")
    typer.echo(f"Files: {len(state.get('files', {}))}")
    typer.echo(f"Output: {target.resolve()}")
    typer.echo(f"Iterations: {state['iteration']}/{max_iterations}")
    build_result = state.get("build_result", {})
    if build_result:
        typer.echo(f"Build: {build_result.get('status', 'unknown')}")
    for issue in state.get("validation_errors", []):
        typer.echo(f"ERROR {issue['file']}: {issue['message']}")
    for issue in state.get("validation_warnings", []):
        typer.echo(f"WARNING {issue['file']}: {issue['message']}")


if __name__ == "__main__":
    app()
