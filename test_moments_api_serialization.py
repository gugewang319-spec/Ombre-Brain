import ast
import asyncio
import copy
import json
from datetime import date, datetime
from pathlib import Path


SERVER_PATH = Path(__file__).with_name("server.py")


def _server_function(name, *, remove_imports=False):
    module = ast.parse(SERVER_PATH.read_text(encoding="utf-8"))
    function = next(
        node
        for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    )
    function = copy.deepcopy(function)
    function.decorator_list = []
    if remove_imports:
        function.body = [
            node
            for node in function.body
            if not isinstance(node, (ast.Import, ast.ImportFrom))
        ]
    return function


def _make_json_safe():
    namespace = {"date": date, "datetime": datetime, "Path": Path, "math": __import__("math")}
    helper = _server_function("make_json_safe")
    exec(compile(ast.Module(body=[helper], type_ignores=[]), str(SERVER_PATH), "exec"), namespace)
    return namespace["make_json_safe"]


def test_make_json_safe_handles_nested_moments_payload_values():
    make_json_safe = _make_json_safe()
    payload = {
        "created_at": datetime(2026, 7, 17, 12, 0),
        "metadata": {"event_date": date(2026, 7, 18), "nested": [datetime(2026, 7, 19, 8, 30)]},
        "edges": [{"created_at": datetime(2026, 7, 20, 9, 45)}],
        "path": Path("/data/buckets/example.md"),
        "tags": {"anchor", "daily"},
        "tuple": ("source", date(2026, 7, 21)),
        "raw": b"moment text",
        "binary": b"\xff",
    }

    safe = make_json_safe(payload)

    assert safe["created_at"] == "2026-07-17T12:00:00"
    assert safe["metadata"]["event_date"] == "2026-07-18"
    assert safe["metadata"]["nested"] == ["2026-07-19T08:30:00"]
    assert safe["edges"][0]["created_at"] == "2026-07-20T09:45:00"
    assert safe["path"] == str(Path("/data/buckets/example.md"))
    assert set(safe["tags"]) == {"anchor", "daily"}
    assert safe["tuple"] == ["source", "2026-07-21"]
    assert safe["raw"] == "moment text"
    assert safe["binary"] == "<bytes:1>"
    json.dumps(safe)


def test_api_moments_returns_json_when_inspection_raises():
    class FakeJSONResponse:
        def __init__(self, content, status_code=200):
            self.content = content
            self.status_code = status_code

    class FakeLogger:
        def __init__(self):
            self.calls = []

        def exception(self, *args, **kwargs):
            self.calls.append((args, kwargs))

    class FakeRequest:
        query_params = {"bucket_id": "bucket-1", "limit": "40"}

    async def failing_inspection(**_kwargs):
        raise RuntimeError("unexpected datetime in diagnostics")

    logger = FakeLogger()
    namespace = {
        "JSONResponse": FakeJSONResponse,
        "_require_dashboard_auth": lambda _request: None,
        "_int_between": lambda value, default, _minimum, _maximum: int(value or default),
        "inspect_moments": failing_inspection,
        "logger": logger,
    }
    api = _server_function("api_moments", remove_imports=True)
    exec(compile(ast.Module(body=[api], type_ignores=[]), str(SERVER_PATH), "exec"), namespace)

    response = asyncio.run(namespace["api_moments"](FakeRequest()))

    assert response.status_code == 500
    assert response.content == {
        "status": "error",
        "error": "moments_inspection_failed",
        "detail": "Moment inspection failed; check server logs for details.",
    }
    assert logger.calls
    json.dumps(response.content)


def test_api_moments_serializes_the_complete_payload_before_responding():
    class FakeJSONResponse:
        def __init__(self, content, status_code=200):
            self.content = content
            self.status_code = status_code

    class FakeRequest:
        query_params = {"bucket_id": "bucket-1", "limit": "40"}

    async def inspection_payload(**_kwargs):
        return {
            "status": "ok",
            "bucket_layer_debug": {"checked_at": datetime(2026, 7, 17, 12, 0)},
            "moments": [
                {
                    "metadata": {"event_date": date(2026, 7, 18)},
                    "created_at": datetime(2026, 7, 19, 8, 30),
                    "source_window": Path("/data/buckets/source.md"),
                }
            ],
            "edges": [{"created_at": datetime(2026, 7, 20, 9, 45), "labels": {"anchor"}}],
        }

    namespace = {
        "JSONResponse": FakeJSONResponse,
        "_require_dashboard_auth": lambda _request: None,
        "_int_between": lambda value, default, _minimum, _maximum: int(value or default),
        "inspect_moments": inspection_payload,
        "make_json_safe": _make_json_safe(),
    }
    api = _server_function("api_moments", remove_imports=True)
    exec(compile(ast.Module(body=[api], type_ignores=[]), str(SERVER_PATH), "exec"), namespace)

    response = asyncio.run(namespace["api_moments"](FakeRequest()))

    assert response.status_code == 200
    assert response.content["bucket_layer_debug"]["checked_at"] == "2026-07-17T12:00:00"
    assert response.content["moments"][0]["metadata"]["event_date"] == "2026-07-18"
    assert response.content["moments"][0]["created_at"] == "2026-07-19T08:30:00"
    assert response.content["moments"][0]["source_window"] == str(Path("/data/buckets/source.md"))
    assert response.content["edges"][0]["created_at"] == "2026-07-20T09:45:00"
    assert response.content["edges"][0]["labels"] == ["anchor"]
    json.dumps(response.content)
