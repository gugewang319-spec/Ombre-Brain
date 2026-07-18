import ast
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo


SERVER_PATH = Path(__file__).with_name("server.py")
BUCKET_MANAGER_PATH = Path(__file__).with_name("bucket_manager.py")
REFLECTION_ENGINE_PATH = Path(__file__).with_name("reflection_engine.py")


def _load_sort_key():
    module = ast.parse(SERVER_PATH.read_text(encoding="utf-8"))
    function = next(
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "_bucket_metadata_time_sort_key"
    )
    namespace = {"datetime": datetime}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(SERVER_PATH), "exec"), namespace)
    return namespace["_bucket_metadata_time_sort_key"]


def _load_datetime_parser():
    module = ast.parse(BUCKET_MANAGER_PATH.read_text(encoding="utf-8"))
    bucket_manager = next(
        node
        for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == "BucketManager"
    )
    function = next(
        node
        for node in bucket_manager.body
        if isinstance(node, ast.FunctionDef) and node.name == "_parse_iso_datetime"
    )
    namespace = {"datetime": datetime, "timezone": timezone, "Optional": Optional}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(BUCKET_MANAGER_PATH), "exec"), namespace)
    return namespace["_parse_iso_datetime"]


class _DatetimeParser:
    _parse_iso_datetime = _load_datetime_parser()


def _sorted_ids(buckets):
    sort_key = _load_sort_key()
    parser = _DatetimeParser()
    return [item["id"] for item in sorted(buckets, key=lambda item: sort_key(item, parser), reverse=True)]


def _load_reflection_methods():
    module = ast.parse(REFLECTION_ENGINE_PATH.read_text(encoding="utf-8"))
    reflection_engine = next(
        node
        for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == "ReflectionEngine"
    )
    methods = [
        node
        for node in reflection_engine.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in {"_candidate_buckets", "_to_local"}
    ]
    namespace = {"Any": Any, "datetime": datetime}
    exec(compile(ast.Module(body=methods, type_ignores=[]), str(REFLECTION_ENGINE_PATH), "exec"), namespace)
    return namespace


def test_mixed_datetime_and_iso_string_sort_without_type_error():
    buckets = [
        {"id": "string", "metadata": {"updated_at": "2026-07-18T10:00:00+00:00"}},
        {"id": "datetime", "metadata": {"updated_at": datetime(2026, 7, 18, 11, 0)}},
    ]

    assert _sorted_ids(buckets) == ["datetime", "string"]


def test_newer_bucket_sorts_before_older_bucket():
    buckets = [
        {"id": "old", "metadata": {"created": "2025-01-01T00:00:00Z"}},
        {"id": "new", "metadata": {"created": "2026-01-01T00:00:00Z"}},
    ]

    assert _sorted_ids(buckets) == ["new", "old"]


def test_timezone_offsets_are_sorted_by_absolute_time():
    buckets = [
        {"id": "earlier", "metadata": {"updated_at": "2026-07-18T12:00:00+08:00"}},
        {"id": "later", "metadata": {"updated_at": "2026-07-18T05:00:00+00:00"}},
    ]

    assert _sorted_ids(buckets) == ["later", "earlier"]


def test_empty_and_invalid_values_sort_last():
    buckets = [
        {"id": "empty", "metadata": {"updated_at": ""}},
        {"id": "valid", "metadata": {"updated_at": "2026-07-18T05:00:00Z"}},
        {"id": "invalid", "metadata": {"updated_at": "not-a-date"}},
    ]

    assert _sorted_ids(buckets)[0] == "valid"
    assert set(_sorted_ids(buckets)[1:]) == {"empty", "invalid"}


def test_all_string_values_sort_normally():
    buckets = [
        {"id": "middle", "metadata": {"updated_at": "2026-06-01T00:00:00Z"}},
        {"id": "new", "metadata": {"updated_at": "2026-07-01T00:00:00Z"}},
        {"id": "old", "metadata": {"updated_at": "2026-05-01T00:00:00Z"}},
    ]

    assert _sorted_ids(buckets) == ["new", "middle", "old"]


def test_all_datetime_values_sort_normally():
    buckets = [
        {"id": "old", "metadata": {"updated_at": datetime(2026, 1, 1, tzinfo=timezone.utc)}},
        {"id": "new", "metadata": {"updated_at": datetime(2026, 1, 2, tzinfo=timezone.utc)}},
    ]

    assert _sorted_ids(buckets) == ["new", "old"]


def test_reflection_candidate_sort_normalizes_mixed_created_values():
    methods = _load_reflection_methods()

    class Engine:
        _candidate_buckets = methods["_candidate_buckets"]
        _to_local = methods["_to_local"]
        config = {
            "reflection": {
                "candidate_limit": 2,
                "candidate_recent_limit": 2,
                "candidate_semantic_limit": 0,
            }
        }
        tz = ZoneInfo("Asia/Shanghai")

    class Manager:
        async def list_all(self, include_archive=True):
            return [
                {"id": "old", "metadata": {"created": "2026-07-18T03:00:00Z"}},
                {"id": "new", "metadata": {"created": datetime(2026, 7, 18, 12, 0)}},
            ]

    candidates = asyncio.run(Engine()._candidate_buckets({"id": "source"}, Manager()))

    assert [item["id"] for item in candidates] == ["new", "old"]
