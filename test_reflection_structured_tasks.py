import asyncio
import logging
from types import SimpleNamespace

import pytest

import reflection_engine as reflection_module
from reflection_engine import ReflectionEngine


def _engine(tmp_path, *, model="deepseek-v4-flash", thinking_mode=""):
    return ReflectionEngine(
        {
            "buckets_dir": str(tmp_path),
            "state_dir": str(tmp_path),
            "dehydration": {},
            "embedding": {},
            "persona": {},
            "reflection": {
                "enabled": True,
                "model": model,
                "thinking_mode": thinking_mode,
            },
        }
    )


def _response(content="{}", finish_reason="stop", *, choices=True):
    response_choices = []
    if choices:
        response_choices.append(
            SimpleNamespace(
                finish_reason=finish_reason,
                message=SimpleNamespace(content=content),
            )
        )
    return SimpleNamespace(choices=response_choices)


def _options(engine, model=None, *, use_daily_client=False):
    return engine._completion_options(
        model=model or engine.model,
        max_tokens=700,
        temperature=0.1,
        use_daily_client=use_daily_client,
    )


def test_deepseek_v4_defaults_to_disabled_thinking(tmp_path):
    engine = _engine(tmp_path)

    assert _options(engine)["extra_body"] == {"thinking": {"type": "disabled"}}


def test_deepseek_v4_explicit_enabled_thinking_wins(tmp_path):
    engine = _engine(tmp_path, thinking_mode="enabled")

    assert _options(engine)["extra_body"] == {"thinking": {"type": "enabled"}}


def test_non_deepseek_model_does_not_receive_thinking_parameter(tmp_path):
    engine = _engine(tmp_path, model="gpt-4.1-mini", thinking_mode="enabled")

    assert "extra_body" not in _options(engine)


def test_dedicated_qwen_uses_only_enable_thinking_false(tmp_path):
    engine = _engine(tmp_path, model="Qwen/Qwen3.5-4B")
    extra_body = _options(engine, use_daily_client=True)["extra_body"]

    assert extra_body == {"enable_thinking": False}
    assert "thinking" not in extra_body


def test_dedicated_deepseek_v4_uses_only_disabled_thinking(tmp_path):
    engine = _engine(tmp_path)
    extra_body = _options(engine, use_daily_client=True)["extra_body"]

    assert extra_body == {"thinking": {"type": "disabled"}}
    assert "enable_thinking" not in extra_body


def test_dedicated_deepseek_v4_explicit_enabled_uses_only_thinking(tmp_path):
    engine = _engine(tmp_path, thinking_mode="enabled")
    extra_body = _options(engine, use_daily_client=True)["extra_body"]

    assert extra_body == {"thinking": {"type": "enabled"}}
    assert "enable_thinking" not in extra_body


@pytest.mark.parametrize(
    "task",
    [
        "memory_enrichment",
        "reflection_daily",
        "daily_chat_memory_summary",
        "daily_activity_summary",
        "daily_chat_memory_candidates",
        "diary_memory_candidate",
    ],
)
def test_all_reflection_json_requests_use_json_response_format(monkeypatch, tmp_path, task):
    engine = _engine(tmp_path)
    calls = []

    async def capture_completion(_client, **payload):
        calls.append(payload)
        return _response()

    monkeypatch.setattr(reflection_module, "create_chat_completion", capture_completion)
    asyncio.run(
        engine._create_structured_completion(
            object(),
            task=task,
            model=engine.model,
            messages=[{"role": "user", "content": "test"}],
            max_tokens=700,
            temperature=0.1,
            use_daily_client=task.startswith("daily_"),
        )
    )

    assert calls[0]["response_format"] == {"type": "json_object"}


def test_reflection_empty_content_is_distinguished(tmp_path, caplog):
    engine = _engine(tmp_path)

    with caplog.at_level(logging.WARNING, logger="ombre_brain.reflection"):
        parsed = engine._parse_structured_completion(
            _response(content="", finish_reason="stop"),
            task="memory_enrichment",
        )

    assert parsed == {}
    assert "returned empty content" in caplog.text
    assert "finish_reason=stop" in caplog.text
    assert "malformed JSON" not in caplog.text


def test_reflection_length_truncation_is_distinguished(tmp_path, caplog):
    engine = _engine(tmp_path)

    with caplog.at_level(logging.WARNING, logger="ombre_brain.reflection"):
        parsed = engine._parse_structured_completion(
            _response(content='{"partial":', finish_reason="length"),
            task="reflection_daily",
        )

    assert parsed == {}
    assert "response truncated" in caplog.text
    assert "finish_reason=length" in caplog.text
    assert "malformed JSON" not in caplog.text


def test_reflection_malformed_json_is_distinguished_without_private_content(tmp_path, caplog):
    engine = _engine(tmp_path)
    private_content = "not-json private memory content"

    with caplog.at_level(logging.WARNING, logger="ombre_brain.reflection"):
        parsed = engine._parse_structured_completion(
            _response(content=private_content, finish_reason="stop"),
            task="diary_memory_candidate",
        )

    assert parsed == {}
    assert "returned malformed JSON" in caplog.text
    assert "finish_reason=stop" in caplog.text
    assert private_content not in caplog.text


def test_reflection_api_error_is_distinguished_and_sanitized(monkeypatch, tmp_path, caplog):
    engine = _engine(tmp_path)

    async def fail_completion(_client, **_payload):
        raise ValueError("private request content and api key")

    monkeypatch.setattr(reflection_module, "create_chat_completion", fail_completion)
    with caplog.at_level(logging.WARNING, logger="ombre_brain.reflection"):
        with pytest.raises(RuntimeError, match="Reflection API call failed: ValueError"):
            asyncio.run(
                engine._create_structured_completion(
                    object(),
                    task="memory_enrichment",
                    model=engine.model,
                    messages=[{"role": "user", "content": "private user conversation"}],
                    max_tokens=700,
                    temperature=0.1,
                )
            )

    assert "API call failed" in caplog.text
    assert "error_type=ValueError" in caplog.text
    assert "private request content" not in caplog.text
    assert "private user conversation" not in caplog.text
