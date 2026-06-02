import json
import sys
import types

from ai_android_app_generator import llm


class FakeModel:
    def __init__(self) -> None:
        self.calls = 0

    def invoke(self, messages):
        self.calls += 1
        if self.calls == 1:
            return FakeResponse(
                {
                    "agent": "validator",
                    "tool_requests": [
                        {"tool": "read_project_files", "paths": ["app/build.gradle.kts"]},
                    ],
                }
            )
        assert "jvmToolchain(17)" in messages[-1][1]
        return FakeResponse({"agent": "validator", "validation_errors": [], "validation_warnings": []})


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.content = json.dumps(payload)


class BrokenJSONThenFixedModel:
    def __init__(self) -> None:
        self.calls = 0

    def invoke(self, messages):
        self.calls += 1
        if self.calls == 1:
            response = types.SimpleNamespace()
            response.content = '{"agent":"architect","architecture":{"pattern":"MVVM" "ui":"Compose"}}'
            return response
        return FakeResponse(
            {
                "agent": "architect",
                "architecture": {
                    "pattern": "MVVM",
                    "ui": "Compose",
                },
            }
        )


def test_openai_agent_can_request_file_context(monkeypatch) -> None:
    fake_model = FakeModel()

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    fake_module = types.SimpleNamespace(ChatOpenAI=lambda **kwargs: fake_model)
    monkeypatch.setitem(sys.modules, "langchain_openai", fake_module)
    monkeypatch.setattr(
        llm,
        "execute_mcp_file_tool_requests",
        lambda files, requests: [
            {
                "tool": "read_project_files",
                "files": {"app/build.gradle.kts": files["app/build.gradle.kts"]},
            }
        ],
    )

    result = llm.ask_openai_agent(
        "validator",
        "Validate project.",
        {"prompt": "Demo"},
        project_files={"app/build.gradle.kts": "kotlin { jvmToolchain(17) }"},
    )

    assert result["validation_errors"] == []
    assert fake_model.calls == 2


def test_openai_agent_repairs_invalid_json_response(monkeypatch) -> None:
    fake_model = BrokenJSONThenFixedModel()

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    fake_module = types.SimpleNamespace(ChatOpenAI=lambda **kwargs: fake_model)
    monkeypatch.setitem(sys.modules, "langchain_openai", fake_module)

    result = llm.ask_openai_agent("architect", "Design architecture.", {"prompt": "Demo"})

    assert result["architecture"]["pattern"] == "MVVM"
    assert fake_model.calls == 2
