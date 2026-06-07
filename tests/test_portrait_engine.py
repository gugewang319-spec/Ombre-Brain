import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from portrait_engine import DailyPortraitMaintainer


@pytest.mark.asyncio
async def test_daily_portrait_maintainer_writes_evidence_bound_state_only(tmp_path, test_config, bucket_mgr):
    evidence_id = await bucket_mgr.create(
        content=(
            "开头原文有一点松动味道，不能只靠短 moment 丢掉。\n\n"
            "### moment\n\n"
            "小雨说最近在把新窗口 handoff 改成画像和近期状态，而不是塞一堆旧记忆。\n\n"
            "### assistant_reflection\n\n"
            "Haven 要把换窗恢复做得轻一点，像醒来，不像翻档案。"
        ),
        name="portrait handoff 方向",
        tags=["project_event"],
        domain=["记忆系统"],
        created="2026-06-07T10:00:00+08:00",
        updated_at="2026-06-07T10:00:00+08:00",
    )
    await bucket_mgr.create(
        content="这条 pinned 不应该被画像维护器自动维护。",
        name="核心规则",
        tags=["core"],
        domain=["规则"],
        pinned=True,
        created="2026-06-07T10:00:00+08:00",
        updated_at="2026-06-07T10:00:00+08:00",
    )
    state_path = tmp_path / "state" / "portrait_state.json"
    cfg = {
        **test_config,
        "portrait": {
            "enabled": True,
            "auto_enabled": True,
            "daily_enabled": True,
            "state_path": str(state_path),
            "material_limit": 8,
            "first_run_material_limit": 8,
        },
    }
    engine = DailyPortraitMaintainer(cfg)

    async def fake_patch(date_key, state, materials, *, initial):
        assert initial is True
        assert [item["bucket_id"] for item in materials["buckets"]] == [evidence_id]
        assert materials["buckets"][0]["path"].endswith(".md")
        assert [item["heading"] for item in materials["buckets"][0]["key_sections"]] == [
            "moment",
            "assistant_reflection",
        ]
        assert "开头原文有一点松动味道" in materials["buckets"][0]["source_excerpt"]
        return {
            "daily_summary": "小雨把换窗恢复方向定到画像和近期状态。",
            "add_recent": [
                {
                    "scope": "user",
                    "text": "小雨正在推进 handoff 画像化，目标是少 token 且更像醒来。",
                    "evidence": [{"bucket_id": evidence_id}],
                    "confidence": 0.82,
                }
            ],
            "move_to_staging": [
                {
                    "scope": "relationship",
                    "text": "换窗连续性优先恢复身份、关系和近期正在做的事。",
                    "evidence": [{"bucket_id": evidence_id}],
                    "confidence": 0.78,
                }
            ],
            "rewrite_mid_term": [
                {
                    "scope": "relationship",
                    "text": "换窗连续性优先恢复身份、关系和近期正在做的事。",
                    "evidence": [{"bucket_id": evidence_id}],
                    "confidence": 0.78,
                }
            ],
            "stable_candidate": [
                {
                    "scope": "relationship",
                    "text": "新窗口不应该依赖广泛旧记忆堆叠。",
                    "evidence": [{"bucket_id": evidence_id}],
                    "confidence": 0.76,
                }
            ],
            "profile_fact_candidate": [
                {
                    "scope": "user",
                    "text": "小雨偏好换窗时先恢复画像和最近事项。",
                    "profile_kind": "preference",
                    "predicate": "handoff_context_shape",
                    "evidence": [{"bucket_id": evidence_id}],
                    "confidence": 0.74,
                }
            ],
            "skip": [],
        }

    engine._generate_patch = fake_patch

    result = await engine.maintain_daily(
        bucket_mgr,
        force=True,
        now=datetime(2026, 6, 7, 23, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert result["status"] == "initialized"
    assert result["patch_counts"]["add_recent"] == 1
    assert state_path.exists()

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["last_run_date"] == "2026-06-07"
    assert state["portrait"]["user"]["recent_buffer"][0]["evidence"] == [{"bucket_id": evidence_id}]
    assert state["portrait"]["relationship"]["staging_pool"][0]["evidence"] == [{"bucket_id": evidence_id}]
    assert state["portrait"]["relationship"]["mid_term_evidence"] == [{"bucket_id": evidence_id}]
    assert state["portrait"]["relationship"]["stable"] == ""
    assert state["stable_candidates"][0]["status"] == "candidate"
    assert state["profile_fact_candidates"][0]["status"] == "candidate"

    all_buckets = await bucket_mgr.list_all(include_archive=True)
    assert len(all_buckets) == 2


def test_portrait_mid_term_rewrite_requires_staging_evidence(tmp_path, test_config):
    state_path = tmp_path / "state" / "portrait_state.json"
    engine = DailyPortraitMaintainer(
        {
            **test_config,
            "portrait": {
                "enabled": True,
                "state_path": str(state_path),
            },
        }
    )
    previous = engine._portrait_snapshot(engine._empty_state())
    materials = {
        "buckets": [{"bucket_id": "fresh-bucket"}],
        "persona_events": [],
        "previous_portrait": previous,
    }

    normalized, rejected = engine._normalize_patch(
        {
            "rewrite_mid_term": [
                {
                    "scope": "relationship",
                    "text": "这条不能直接从当天新材料写成 mid-term。",
                    "evidence": [{"bucket_id": "fresh-bucket"}],
                }
            ]
        },
        materials,
    )

    assert normalized["rewrite_mid_term"] == []
    assert rejected[0]["reason"] == "missing_staging_evidence"

    normalized, rejected = engine._normalize_patch(
        {
            "move_to_staging": [
                {
                    "scope": "relationship",
                    "text": "先放入 staging 的观察。",
                    "evidence": [{"bucket_id": "fresh-bucket"}],
                }
            ],
            "rewrite_mid_term": [
                {
                    "scope": "relationship",
                    "text": "这条可以从本次 staging 证据综合。",
                    "evidence": [{"bucket_id": "fresh-bucket"}],
                }
            ],
        },
        materials,
    )

    assert rejected == []
    assert normalized["move_to_staging"][0]["evidence"] == [{"bucket_id": "fresh-bucket"}]
    assert normalized["rewrite_mid_term"][0]["evidence"] == [{"bucket_id": "fresh-bucket"}]


def test_handoff_recent_continuity_sorts_equal_timestamps_without_dict_compare(tmp_path, test_config):
    state_path = tmp_path / "state" / "portrait_state.json"
    engine = DailyPortraitMaintainer(
        {
            **test_config,
            "portrait": {
                "enabled": True,
                "state_path": str(state_path),
            },
        }
    )
    state = engine._empty_state()
    same_time = "2026-06-07T01:25:42+00:00"
    state["portrait"]["user"]["recent_buffer"].append(
        {
            "text": "小雨最近在调整换窗 handoff。",
            "evidence": [{"bucket_id": "u"}],
            "updated_at": same_time,
        }
    )
    state["portrait"]["relationship"]["recent_buffer"].append(
        {
            "text": "关系画像要优先于旧记忆堆。",
            "evidence": [{"bucket_id": "r"}],
            "updated_at": same_time,
        }
    )
    engine.save_state(state)

    sections = engine.build_handoff_sections(max_recent_items=4)

    assert "小雨最近在调整换窗 handoff" in sections["recent_continuity"]
    assert "关系画像要优先于旧记忆堆" in sections["recent_continuity"]
