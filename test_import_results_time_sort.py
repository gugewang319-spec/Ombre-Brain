import ast
import asyncio
import copy
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


SERVER_PATH = Path(__file__).with_name("server.py")
BUCKET_MANAGER_PATH = Path(__file__).with_name("bucket_manager.py")


def _load_bucket_datetime_parser():
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


def _load_import_results_route(namespace):
    module = ast.parse(SERVER_PATH.read_text(encoding="utf-8"))
    function = copy.deepcopy(
        next(
            node
            for node in module.body
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "api_import_results"
        )
    )
    function.decorator_list = []
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(SERVER_PATH), "exec"), namespace)
    return namespace["api_import_results"]


class _Response:
    def __init__(self, content, status_code=200):
        self.content = content
        self.status_code = status_code


class _Request:
    query_params = {"limit": "30"}


class _BucketManager:
    _parse_iso_datetime = _load_bucket_datetime_parser()

    def __init__(self, buckets):
        self.buckets = buckets

    async def list_all(self, include_archive=False):
        return list(self.buckets)


def _bucket(bucket_id, created):
    return {
        "id": bucket_id,
        "metadata": {
            "name": bucket_id,
            "created": created,
            "type": "dynamic",
            "domain": [],
            "tags": [],
            "importance": 5,
        },
        "content": bucket_id,
    }


def _result_ids(buckets):
    namespace = {
        "JSONResponse": _Response,
        "_require_dashboard_auth": lambda _request: None,
        "bucket_mgr": _BucketManager(buckets),
        "datetime": datetime,
    }
    route = _load_import_results_route(namespace)
    response = asyncio.run(route(_Request()))
    assert response.status_code == 200
    return [item["id"] for item in response.content["buckets"]]


def test_import_results_sorts_mixed_datetime_and_string():
    buckets = [
        _bucket("string", "2026-07-18T10:00:00Z"),
        _bucket("datetime", datetime(2026, 7, 18, 11, 0)),
    ]

    assert _result_ids(buckets) == ["datetime", "string"]


def test_import_results_sorts_iso_times_newest_first():
    buckets = [
        _bucket("old", "2026-01-01T00:00:00Z"),
        _bucket("new", "2026-02-01T00:00:00Z"),
    ]

    assert _result_ids(buckets) == ["new", "old"]


def test_import_results_sorts_timezone_strings_by_absolute_time():
    buckets = [
        _bucket("earlier", "2026-07-18T12:00:00+08:00"),
        _bucket("later", "2026-07-18T05:00:00+00:00"),
    ]

    assert _result_ids(buckets) == ["later", "earlier"]


def test_import_results_sorts_empty_created_last():
    buckets = [
        _bucket("empty", None),
        _bucket("valid", "2026-07-18T05:00:00Z"),
    ]

    assert _result_ids(buckets) == ["valid", "empty"]


def test_import_results_sorts_invalid_created_last():
    buckets = [
        _bucket("invalid", "not-a-date"),
        _bucket("valid", "2026-07-18T05:00:00Z"),
    ]

    assert _result_ids(buckets) == ["valid", "invalid"]


def test_import_results_sorts_all_datetime_values():
    buckets = [
        _bucket("old", datetime(2026, 1, 1, tzinfo=timezone.utc)),
        _bucket("new", datetime(2026, 1, 2, tzinfo=timezone.utc)),
    ]

    assert _result_ids(buckets) == ["new", "old"]


def test_import_results_sorts_all_string_values():
    buckets = [
        _bucket("middle", "2026-06-01T00:00:00Z"),
        _bucket("new", "2026-07-01T00:00:00Z"),
        _bucket("old", "2026-05-01T00:00:00Z"),
    ]

    assert _result_ids(buckets) == ["new", "middle", "old"]
