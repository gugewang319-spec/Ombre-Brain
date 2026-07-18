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


def _options(engine, model=None):
    return engine._completion_options(
        model=model or engine.model,
        max_tokens=700,
        temperature=0.1,
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


def test_reflection_structured_request_uses_json_response_format(tmp_path):
    engine = _engine(tmp_path)

    assert _options(engine)["response_format"] == {"type": "json_object"}


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
