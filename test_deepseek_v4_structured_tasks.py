import ast
import asyncio
import copy
import json
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from dehydrator import Dehydrator
from persona_engine import PersonaStateEngine


ROOT = Path(__file__).parent
SERVER_PATH = ROOT / "server.py"
GATEWAY_PATH = ROOT / "gateway.py"
DASHBOARD_PATH = ROOT / "dashboard.html"


class FakeCompletions:
    def __init__(self, *, content="{}", finish_reason="stop", choices=True, error=None):
        self.calls = []
        self.content = content
        self.finish_reason = finish_reason
        self.choices = choices
        self.error = error

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        choices = []
        if self.choices:
            choices = [
                SimpleNamespace(
                    finish_reason=self.finish_reason,
                    message=SimpleNamespace(content=self.content),
                )
            ]
        return SimpleNamespace(choices=choices)


def _persona_engine(monkeypatch, tmp_path, **persona_overrides):
    for env_name in (
        "OMBRE_PERSONA_API_KEY",
        "OMBRE_PERSONA_BASE_URL",
        "OMBRE_PERSONA_MODEL",
        "OMBRE_PERSONA_DB_PATH",
    ):
        monkeypatch.delenv(env_name, raising=False)
    persona = {
        "enabled": True,
        "mode": "llm",
        "model": "deepseek-v4-flash",
        **persona_overrides,
    }
    return PersonaStateEngine(
        {
            "persona": persona,
            "state_dir": str(tmp_path),
            "buckets_dir": str(tmp_path),
        }
    )


async def _evaluate(engine, completions):
    engine.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    result = await engine._evaluate_exchange(
        session_id="session-test",
        user_message="private user message",
        assistant_response="private assistant response",
        global_state={},
        session_state={},
        recalled_memory_ids=[],
        tool_summary="",
    )
    return result, completions.calls


def test_persona_v4_defaults_to_non_thinking_json_and_800_tokens(monkeypatch, tmp_path):
    engine = _persona_engine(monkeypatch, tmp_path)
    (evaluation, _raw, error), calls = asyncio.run(_evaluate(engine, FakeCompletions()))

    assert evaluation is not None
    assert error is None
    assert len(calls) == 1
    assert calls[0]["extra_body"] == {"thinking": {"type": "disabled"}}
    assert calls[0]["response_format"] == {"type": "json_object"}
    assert calls[0]["max_tokens"] == 800


def test_persona_explicit_thinking_and_max_tokens_override_defaults(monkeypatch, tmp_path):
    engine = _persona_engine(
        monkeypatch,
        tmp_path,
        thinking_mode="enabled",
        max_tokens=1234,
    )
    (_result, calls) = asyncio.run(_evaluate(engine, FakeCompletions()))

    assert calls[0]["extra_body"] == {"thinking": {"type": "enabled"}}
    assert calls[0]["max_tokens"] == 1234


def test_persona_non_deepseek_model_does_not_receive_thinking_parameter(monkeypatch, tmp_path):
    engine = _persona_engine(monkeypatch, tmp_path, model="gpt-4.1-mini")
    (_result, calls) = asyncio.run(_evaluate(engine, FakeCompletions()))

    assert "extra_body" not in calls[0]
    assert calls[0]["response_format"] == {"type": "json_object"}


def test_persona_conflict_detector_uses_structured_v4_request_and_sanitizes_unicode(
    monkeypatch,
    tmp_path,
):
    engine = _persona_engine(monkeypatch, tmp_path, conflict_nudge_enabled=True)
    completions = FakeCompletions(
        content='{"signal": false, "kind": "none", "confidence": 0}'
    )
    engine.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    result = asyncio.run(engine.detect_conflict_nudge("conflict \ud800 signal"))

    assert result["reason"] == "no_signal"
    assert len(completions.calls) == 1
    request = completions.calls[0]
    assert request["extra_body"] == {"thinking": {"type": "disabled"}}
    assert request["response_format"] == {"type": "json_object"}
    assert request["max_tokens"] == 120
    assert request["timeout"] == 4.0
    assert "\ud800" not in request["messages"][1]["content"]


@pytest.mark.parametrize(
    ("content", "finish_reason", "expected_error", "expected_log"),
    [
        ("", "stop", "persona LLM returned empty content", "returned empty content"),
        (
            '{"event_type": "neutral"',
            "length",
            "persona LLM response truncated (finish_reason=length)",
            "response truncated",
        ),
        ("not-json", "stop", "persona LLM returned malformed JSON", "malformed JSON"),
    ],
)
def test_persona_response_failures_are_distinguished_without_private_log_content(
    monkeypatch,
    tmp_path,
    caplog,
    content,
    finish_reason,
    expected_error,
    expected_log,
):
    engine = _persona_engine(monkeypatch, tmp_path)
    with caplog.at_level(logging.WARNING, logger="ombre_brain.persona"):
        (evaluation, _raw, error), _calls = asyncio.run(
            _evaluate(
                engine,
                FakeCompletions(content=content, finish_reason=finish_reason),
            )
        )

    assert evaluation is None
    assert error == expected_error
    assert expected_log in caplog.text
    assert "private user message" not in caplog.text
    assert "private assistant response" not in caplog.text


def test_persona_api_exception_is_distinguished_and_sanitized(monkeypatch, tmp_path, caplog):
    engine = _persona_engine(monkeypatch, tmp_path)
    with caplog.at_level(logging.WARNING, logger="ombre_brain.persona"):
        (evaluation, raw, error), _calls = asyncio.run(
            _evaluate(engine, FakeCompletions(error=RuntimeError("secret request detail")))
        )

    assert evaluation is None
    assert raw == ""
    assert error == "persona LLM API call failed: RuntimeError"
    assert "API call failed" in caplog.text
    assert "secret request detail" not in caplog.text


def test_dehydrator_v4_structured_options_disable_thinking_and_enable_json(tmp_path):
    dehydrator = Dehydrator(
        {
            "buckets_dir": str(tmp_path),
            "dehydration": {
                "model": "deepseek-v4-flash",
                "temperature": 0.1,
            }
        }
    )

    structured = dehydrator._completion_options(
        max_tokens=256,
        temperature=0.1,
        json_response=True,
    )
    plain_text = dehydrator._completion_options(max_tokens=1024, temperature=0.1)

    assert structured["extra_body"] == {"thinking": {"type": "disabled"}}
    assert structured["response_format"] == {"type": "json_object"}
    assert plain_text["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "response_format" not in plain_text


def test_dehydrator_explicit_thinking_wins_and_non_deepseek_stays_compatible(tmp_path):
    enabled = Dehydrator(
        {
            "buckets_dir": str(tmp_path),
            "dehydration": {"model": "deepseek-v4-flash", "thinking_mode": "enabled"},
        }
    )
    compatible = Dehydrator(
        {
            "buckets_dir": str(tmp_path),
            "dehydration": {"model": "gpt-4.1-mini"},
        }
    )

    assert enabled._completion_options(max_tokens=256, temperature=0.1)["extra_body"] == {
        "thinking": {"type": "enabled"}
    }
    assert "extra_body" not in compatible._completion_options(max_tokens=256, temperature=0.1)


def _server_function(name):
    module = ast.parse(SERVER_PATH.read_text(encoding="utf-8"))
    function = next(
        node
        for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    )
    function = copy.deepcopy(function)
    function.decorator_list = []
    return function


def _gateway_method(class_name, method_name):
    module = ast.parse(GATEWAY_PATH.read_text(encoding="utf-8"))
    class_node = next(
        node
        for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    method = next(
        node
        for node in class_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == method_name
    )
    method = copy.deepcopy(method)
    method.decorator_list = []
    return method


def test_dashboard_api_persists_and_hot_updates_persona_controls(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "persona:\n  model: old-model\n  unknown_persona_field: keep-me\nunknown_root: keep-root\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OMBRE_CONFIG_PATH", str(config_path))
    monkeypatch.delenv("OMBRE_RUNTIME_CONFIG_PATH", raising=False)

    hot_updates = []

    async def hot_update(payload):
        hot_updates.append(copy.deepcopy(payload))
        return "gateway_hot_updated"

    class FakePersonaStateEngine:
        def __init__(self, config):
            persona = config.get("persona", {})
            self.enabled = persona.get("enabled", True)
            self.model = persona.get("model", "")
            self.base_url = persona.get("base_url", "")
            self.thinking_mode = persona.get("thinking_mode", "")
            self.event_recording_enabled = persona.get("event_recording_enabled", True)
            self.conflict_nudge_enabled = persona.get("conflict_nudge_enabled", False)
            self.api_key = persona.get("api_key", "")

    class FakeJSONResponse:
        def __init__(self, content, status_code=200):
            self.content = content
            self.status_code = status_code

    class FakeRequest:
        async def json(self):
            return {
                "persona": {
                    "model": "deepseek-v4-flash",
                    "thinking_mode": "enabled",
                    "conflict_nudge_enabled": True,
                },
                "persist": True,
            }

    runtime_config = {
        "persona": {"model": "old-model", "unknown_persona_field": "keep-me"},
        "state_dir": str(tmp_path / "state"),
        "buckets_dir": str(tmp_path / "buckets"),
    }
    namespace = {
        "JSONResponse": FakeJSONResponse,
        "PersonaStateEngine": FakePersonaStateEngine,
        "_require_dashboard_auth": lambda _request: None,
        "_hot_update_gateway_config": hot_update,
        "config": runtime_config,
        "persona_engine": FakePersonaStateEngine(runtime_config),
        "os": __import__("os"),
        "__file__": str(SERVER_PATH),
    }
    function = _server_function("api_config_update")
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(SERVER_PATH), "exec"), namespace)

    response = asyncio.run(namespace["api_config_update"](FakeRequest()))
    saved = yaml.safe_load(config_path.read_text(encoding="utf-8"))

    assert response.status_code == 200
    assert "persona.thinking_mode" in response.content["updated"]
    assert "persona.conflict_nudge_enabled" in response.content["updated"]
    assert namespace["persona_engine"].thinking_mode == "enabled"
    assert namespace["persona_engine"].conflict_nudge_enabled is True
    assert hot_updates[-1]["persona"]["thinking_mode"] == "enabled"
    assert hot_updates[-1]["persona"]["conflict_nudge_enabled"] is True
    assert saved["persona"]["thinking_mode"] == "enabled"
    assert saved["persona"]["conflict_nudge_enabled"] is True
    assert saved["persona"]["unknown_persona_field"] == "keep-me"
    assert saved["unknown_root"] == "keep-root"


def test_gateway_persona_hot_update_rebuilds_engine_with_merged_controls(monkeypatch):
    captured = []

    class FakePersonaStateEngine:
        def __init__(self, config):
            captured.append(copy.deepcopy(config))
            self.thinking_mode = config["persona"].get("thinking_mode", "")
            self.conflict_nudge_enabled = config["persona"].get("conflict_nudge_enabled", False)

    namespace = {
        "Any": Any,
        "PersonaStateEngine": FakePersonaStateEngine,
        "os": __import__("os"),
    }
    method = _gateway_method("GatewayService", "_apply_persona_config")
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(GATEWAY_PATH), "exec"), namespace)
    service = SimpleNamespace(config={"persona": {}}, persona_engine=SimpleNamespace())

    updated = namespace["_apply_persona_config"](
        service,
        {"thinking_mode": "disabled", "conflict_nudge_enabled": True},
    )

    assert updated == ["persona.conflict_nudge_enabled", "persona.thinking_mode"]
    assert service.persona_engine.thinking_mode == "disabled"
    assert service.persona_engine.conflict_nudge_enabled is True
    assert captured[-1]["persona"]["thinking_mode"] == "disabled"
    assert captured[-1]["persona"]["conflict_nudge_enabled"] is True


def test_dashboard_exposes_loads_and_saves_persona_controls():
    source = DASHBOARD_PATH.read_text(encoding="utf-8")
    server_source = SERVER_PATH.read_text(encoding="utf-8")

    assert 'id="cfg-persona-thinking"' in source
    assert "cfg.persona.thinking_mode" in source
    assert "thinking_mode: document.getElementById('cfg-persona-thinking').value" in source
    assert 'id="cfg-persona-conflict-nudge"' in source
    assert "cfg.persona.conflict_nudge_enabled" in source
    assert "conflict_nudge_enabled: document.getElementById('cfg-persona-conflict-nudge').value" in source
    assert '"conflict_nudge_enabled": _bool_value(' in server_source
