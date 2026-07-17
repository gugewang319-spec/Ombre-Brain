import ast
import asyncio
import copy
import json
from pathlib import Path

from utils import JsonSafeJSONResponse


GATEWAY_PATH = Path(__file__).with_name("gateway.py")


def _gateway_method(class_name: str, method_name: str):
    module = ast.parse(GATEWAY_PATH.read_text(encoding="utf-8"))
    class_node = next(
        node for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    method = next(
        node for node in class_node.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == method_name
    )
    method = copy.deepcopy(method)
    method.decorator_list = []
    return method


def test_json_response_encodes_surrogate_path_and_dict_key():
    invalid_path = "/data/buckets/feel/\udcb5\udca6xxx"

    response = JsonSafeJSONResponse(
        {
            "path": Path(invalid_path),
            "domains": {"feel\udcb5": 1},
        }
    )
    payload = json.loads(response.body.decode("utf-8"))

    assert response.status_code == 200
    assert "\ufffd\ufffdxxx" in payload["path"]
    assert payload["domains"] == {"feel\ufffd": 1}


def test_gateway_health_uses_json_safe_response():
    class FakeService:
        async def health_payload(self):
            return {
                "status": "ok",
                "buckets": {
                    "domains": {
                        "/data/buckets/feel/\udcb5\udca6xxx": 1,
                    }
                },
            }

    class FakeLogger:
        def exception(self, *_args, **_kwargs):
            raise AssertionError("health response should not fail encoding")

    namespace = {
        "JSONResponse": JsonSafeJSONResponse,
        "Request": object,
        "logger": FakeLogger(),
    }
    method = _gateway_method("GatewayService", "handle_health")
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(GATEWAY_PATH), "exec"), namespace)

    response = asyncio.run(namespace["handle_health"](FakeService(), None))
    payload = json.loads(response.body.decode("utf-8"))

    assert response.status_code == 200
    assert payload["status"] == "ok"
    assert payload["buckets"]["domains"] == {
        "/data/buckets/feel/\ufffd\ufffdxxx": 1,
    }
