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


def test_openai_agent_can_request_file_context(monkeypatch) -> None:
    fake_model = FakeModel()

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    fake_module = types.SimpleNamespace(ChatOpenAI=lambda **kwargs: fake_model)
    monkeypatch.setitem(sys.modules, "langchain_openai", fake_module)

    result = llm.ask_openai_agent(
        "validator",
        "Validate project.",
        {"prompt": "Demo"},
        project_files={"app/build.gradle.kts": "kotlin { jvmToolchain(17) }"},
    )

    assert result["validation_errors"] == []
    assert fake_model.calls == 2
