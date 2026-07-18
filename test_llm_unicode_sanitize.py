import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from portrait_engine import DailyPortraitMaintainer
from utils import create_chat_completion, dumps_llm_payload, sanitize_unicode


class FakeCompletions:
    def __init__(self):
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(content="{}"),
                )
            ]
        )


def _fake_client():
    completions = FakeCompletions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return client, completions


def test_sanitize_unicode_is_idempotent_and_preserves_normal_json_values():
    payload = {
        "text": "正常 Unicode 🌈",
        "integer": 7,
        "float": 1.25,
        "enabled": True,
        "missing": None,
        "nested": ["value", {"count": 2}],
        "broken\udcb5": Path("buckets") / "entry\udca6.md",
    }

    safe = sanitize_unicode(payload)

    assert safe["text"] == payload["text"]
    assert safe["integer"] == 7
    assert safe["float"] == 1.25
    assert safe["enabled"] is True
    assert safe["missing"] is None
    assert safe["nested"] == payload["nested"]
    assert isinstance(safe, dict)
    assert isinstance(safe["nested"], list)
    assert sanitize_unicode(safe) == safe


def test_sanitize_unicode_replaces_surrogate_in_dict_key_without_dropping_value():
    payload = {"bucket\udcb5": {"value": 7}}

    safe = sanitize_unicode(payload)

    assert safe == {"bucket\ufffd": {"value": 7}}
    assert len(safe) == len(payload)
    json.dumps(safe, ensure_ascii=False).encode("utf-8")


def test_sanitize_unicode_converts_path_and_replaces_surrogate():
    path = Path("buckets") / "feel" / "broken\udca6.md"

    safe = sanitize_unicode(path)

    assert isinstance(safe, str)
    assert safe.endswith("broken\ufffd.md")
    assert "broken.md" not in safe
    safe.encode("utf-8")


def test_bucket_path_payload_serializes_with_replacement_and_structure_intact():
    payload = {
        "buckets": [
            {
                "id": "bucket-1",
                "path": Path("buckets") / "feel" / "entry\udcb5.md",
                "metadata": {"source_path": "vault/entry\udca6.md"},
            }
        ]
    }

    encoded = dumps_llm_payload(payload, ensure_ascii=False)
    decoded = json.loads(encoded)

    encoded.encode("utf-8")
    assert decoded["buckets"][0]["id"] == "bucket-1"
    assert decoded["buckets"][0]["path"].endswith("entry\ufffd.md")
    assert decoded["buckets"][0]["metadata"]["source_path"] == "vault/entry\ufffd.md"


def test_chat_completion_sanitizes_the_complete_outbound_payload():
    client, completions = _fake_client()

    asyncio.run(
        create_chat_completion(
            client,
            model="model-test",
            messages=[{"role": "user", "content": "raw\udcb5message"}],
            metadata={"key\udca6": Path("bucket\udcb5.md")},
        )
    )

    call = completions.calls[0]
    assert call["messages"][0]["content"] == "raw\ufffdmessage"
    assert call["metadata"] == {"key\ufffd": "bucket\ufffd.md"}
    json.dumps(call, ensure_ascii=False).encode("utf-8")


def test_portrait_payload_with_surrogate_bucket_path_serializes_successfully():
    client, completions = _fake_client()
    portrait = object.__new__(DailyPortraitMaintainer)
    portrait.client = client
    portrait.model = "deepseek-v4-flash"
    portrait.temperature = 0.1
    portrait.json_response_format = True
    portrait.thinking_mode = "disabled"
    portrait._prompt = lambda: "Return JSON"
    payload = {
        "date": "2026-07-18",
        "memory_materials": {
            "buckets": [
                {
                    "id": "portrait-source",
                    "path": Path("buckets") / "dynamic" / "portrait\udcb5.md",
                    "content": "kept\udca6content",
                }
            ]
        },
    }

    asyncio.run(portrait._create_patch_completion(payload, max_tokens=800))

    call = completions.calls[0]
    user_payload = json.loads(call["messages"][1]["content"])
    bucket = user_payload["memory_materials"]["buckets"][0]
    assert bucket["id"] == "portrait-source"
    assert bucket["path"].endswith("portrait\ufffd.md")
    assert bucket["content"] == "kept\ufffdcontent"
    json.dumps(call, ensure_ascii=False).encode("utf-8")
