import asyncio
import logging
import os
import queue
import threading
import time
from datetime import datetime as real_datetime, timezone
from logging.handlers import QueueHandler, RotatingFileHandler

import pytest

import gateway
from gateway import GatewayService


MODEL = "stream-model"
SESSION = "stream-session"
ROUTE = {
    "upstream": {
        "name": "stream-upstream",
        "protocol": "openai",
        "api_key": "sk-upstream-private",
    },
    "public_model": MODEL,
    "upstream_model": MODEL,
}


def _reset_sse_diagnostics_file_logger():
    gateway._stop_sse_diagnostics_file_logging()
    for handler in list(gateway._sse_diagnostics_file_logger.handlers):
        if isinstance(handler, QueueHandler):
            gateway._sse_diagnostics_file_logger.removeHandler(handler)
            handler.close()
    gateway._sse_diagnostics_file_handler = None
    gateway._sse_diagnostics_queue_handler = None
    gateway._sse_diagnostics_queue_listener = None
    gateway._sse_diagnostics_queue = None
    gateway._sse_diagnostics_file_initialized = False
    gateway._sse_diagnostics_file_disabled = False
    gateway._sse_diagnostics_file_warning_emitted = False


@pytest.fixture(autouse=True)
def isolated_sse_file_log(monkeypatch, tmp_path):
    _reset_sse_diagnostics_file_logger()
    state_dir = tmp_path / "state"
    monkeypatch.setenv("OMBRE_STATE_DIR", str(state_dir))
    monkeypatch.delenv("OMBRE_CONFIG_PATH", raising=False)
    gateway._initialize_sse_diagnostics_file_logging()
    yield state_dir
    _reset_sse_diagnostics_file_logger()


def _wait_until(predicate, timeout=3.0):
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return bool(predicate())


def _read_log_when_contains(path, expected, timeout=3.0):
    content = ""

    def contains_expected():
        nonlocal content
        if path.exists():
            content = path.read_text(encoding="utf-8")
        return expected in content

    assert _wait_until(contains_expected, timeout=timeout)
    return content


class FakeUpstreamResponse:
    status_code = 200
    headers = {"content-type": "text/event-stream"}

    def __init__(self, chunks=(), *, read_error=None, close_error=None):
        self.chunks = list(chunks)
        self.read_error = read_error
        self.close_error = close_error
        self.closed = False

    async def aiter_bytes(self):
        for chunk in self.chunks:
            yield chunk
        if self.read_error is not None:
            raise self.read_error

    async def aclose(self):
        self.closed = True
        if self.close_error is not None:
            raise self.close_error


def _service(response, *, finalize_error=None):
    service = GatewayService.__new__(GatewayService)
    finalize_calls = []

    service._resolve_upstream_for_model = lambda model: ROUTE
    service._upstream_uses_anthropic_protocol = lambda upstream: False

    async def open_upstream_stream(route, payload):
        return response

    service._open_upstream_stream = open_upstream_stream
    service._open_anthropic_upstream_stream = open_upstream_stream
    service._new_stream_capture_state = lambda: {"seen_done": False}

    def capture(state, chunk, final=False):
        if b"[DONE]" in chunk or b'"type":"message_stop"' in chunk:
            state["seen_done"] = True

    service._consume_stream_capture_chunk = capture
    service._consume_anthropic_stream_capture_chunk = capture

    async def finalize(**kwargs):
        finalize_calls.append(kwargs)
        if finalize_error is not None:
            raise finalize_error

    service._finalize_stream_turn = finalize
    return service, finalize_calls


async def _collect(response):
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk)
    return b"".join(chunks)


async def _raw_openai_response(service, payload=None):
    return await service._stream_upstream(
        payload
        or {
            "model": MODEL,
            "messages": [{"role": "user", "content": "PRIVATE_MESSAGE_BODY"}],
        },
        SESSION,
        [],
        "PRIVATE_MESSAGE_BODY",
    )


async def test_raw_openai_stream_bytes_are_unchanged_and_logs_are_private(
    caplog,
    monkeypatch,
    isolated_sse_file_log,
):
    chunks = [
        b'data: {"choices":[{"delta":{"content":"PRIVATE_ASSISTANT_BODY"}}]}\n\n',
        b'data: [DONE]\n\n',
    ]
    upstream_response = FakeUpstreamResponse(chunks)
    service, finalize_calls = _service(upstream_response)
    monkeypatch.setattr(gateway.secrets, "token_hex", lambda size: "a1b2c3d4")
    caplog.set_level(logging.INFO, logger="ombre_brain.gateway")

    response = await _raw_openai_response(
        service,
        {
            "model": MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": "PRIVATE_MESSAGE_BODY",
                    "reasoning": "PRIVATE_REASONING_BODY",
                }
            ],
            "token": "PRIVATE_PAYLOAD_TOKEN",
        },
    )

    assert await _collect(response) == b"".join(chunks)
    file_log = _read_log_when_contains(
        isolated_sse_file_log / "sse-stream-diagnostics.log",
        "Gateway SSE stream completed",
    )
    file_lines = file_log.splitlines()
    assert upstream_response.closed is True
    assert len(finalize_calls) == 1
    assert "Gateway SSE stream started" in caplog.text
    assert "Gateway stream first chunk" in caplog.text
    assert "Gateway SSE stream completed" in caplog.text
    assert "stream_id=a1b2c3d4" in caplog.text
    assert "message_count=1" in caplog.text
    assert "chunk_count=2" in caplog.text
    assert f"total_bytes={sum(map(len, chunks))}" in caplog.text
    assert "seen_done=True" in caplog.text
    assert "finalize_attempted=True" in caplog.text
    assert "finalize_completed=True" in caplog.text
    assert len(file_lines) == 3
    assert "Gateway SSE stream started" in file_lines[0]
    assert "Gateway stream first chunk" in file_lines[1]
    assert "Gateway SSE stream completed" in file_lines[2]
    for line in file_lines:
        assert line[:4].isdigit()
        assert "Z INFO " in line
        for field in (
            "stream_id=",
            "session=",
            "model=",
            "event=",
            "stage=",
            "exception_type=",
            "chunk_count=",
            "total_bytes=",
            "elapsed_ms=",
        ):
            assert field in line
    for private_value in (
        "PRIVATE_MESSAGE_BODY",
        "PRIVATE_ASSISTANT_BODY",
        "PRIVATE_REASONING_BODY",
        "PRIVATE_PAYLOAD_TOKEN",
        "sk-upstream-private",
    ):
        assert private_value not in caplog.text
        assert private_value not in file_log


def test_sse_file_rotation_configuration(isolated_sse_file_log):
    service = GatewayService.__new__(GatewayService)
    service._log_sse_stream_started(
        stream_id="rotation",
        session_id=SESSION,
        model=MODEL,
        upstream_status=200,
        message_count=1,
        started_at=gateway.time.perf_counter(),
    )

    handler = gateway._sse_diagnostics_file_handler
    assert isinstance(handler, RotatingFileHandler)
    assert handler.maxBytes == 2 * 1024 * 1024
    assert handler.backupCount == 3
    assert handler.mode == "a"
    assert handler.encoding.lower().replace("-", "") == "utf8"
    assert handler.baseFilename == os.path.abspath(
        isolated_sse_file_log / "sse-stream-diagnostics.log"
    )


def test_sse_queue_listener_initializes_only_once():
    listener = gateway._sse_diagnostics_queue_listener
    queue_handler = gateway._sse_diagnostics_queue_handler
    diagnostic_queue = gateway._sse_diagnostics_queue
    assert listener is not None
    assert queue_handler is not None
    assert diagnostic_queue is not None
    assert diagnostic_queue.maxsize == 1000

    gateway._initialize_sse_diagnostics_file_logging()
    gateway._initialize_sse_diagnostics_file_logging()

    assert gateway._sse_diagnostics_queue_listener is listener
    assert gateway._sse_diagnostics_queue_handler is queue_handler
    assert gateway._sse_diagnostics_queue is diagnostic_queue
    assert sum(
        isinstance(handler, gateway._BestEffortQueueHandler)
        for handler in gateway._sse_diagnostics_file_logger.handlers
    ) == 1


def test_sse_file_log_path_resolution_priority(monkeypatch, tmp_path):
    state_dir = tmp_path / "explicit-state"
    config_path = tmp_path / "config-state" / "config.yaml"
    monkeypatch.setenv("OMBRE_STATE_DIR", str(state_dir))
    monkeypatch.setenv("OMBRE_CONFIG_PATH", str(config_path))
    assert gateway._resolve_sse_diagnostics_log_path() == os.path.abspath(
        state_dir / "sse-stream-diagnostics.log"
    )

    monkeypatch.delenv("OMBRE_STATE_DIR")
    assert gateway._resolve_sse_diagnostics_log_path() == os.path.abspath(
        config_path.parent / "sse-stream-diagnostics.log"
    )

    monkeypatch.delenv("OMBRE_CONFIG_PATH")
    assert gateway._resolve_sse_diagnostics_log_path() == os.path.abspath(
        "/data/state/sse-stream-diagnostics.log"
    )


async def test_slow_file_handler_does_not_block_sse_generator(monkeypatch):
    chunks = [b"data: immediate\n\n", b"data: [DONE]\n\n"]
    upstream_response = FakeUpstreamResponse(chunks)
    service, _ = _service(upstream_response)
    handler = gateway._sse_diagnostics_file_handler
    assert handler is not None
    original_emit = handler.emit
    slow_started = threading.Event()
    slow_once = True

    def slow_emit(record):
        nonlocal slow_once
        if slow_once:
            slow_once = False
            slow_started.set()
            time.sleep(0.5)
        original_emit(record)

    monkeypatch.setattr(handler, "emit", slow_emit)
    service._log_sse_stream_started(
        stream_id="slow-warmup",
        session_id=SESSION,
        model=MODEL,
        upstream_status=200,
        message_count=1,
        started_at=time.perf_counter(),
    )
    assert slow_started.wait(timeout=1.0)

    started_at = time.perf_counter()
    response = await _raw_openai_response(service)
    output = await _collect(response)
    elapsed = time.perf_counter() - started_at

    assert output == b"".join(chunks)
    assert elapsed < 0.25
    assert upstream_response.closed is True


async def test_full_sse_diagnostics_queue_drops_without_blocking_stream(caplog):
    _reset_sse_diagnostics_file_logger()
    diagnostic_queue = queue.Queue(maxsize=1)
    diagnostic_queue.put_nowait(logging.makeLogRecord({"msg": "occupied"}))
    queue_handler = gateway._BestEffortQueueHandler(diagnostic_queue)
    queue_handler.setLevel(logging.INFO)
    gateway._sse_diagnostics_file_logger.setLevel(logging.INFO)
    gateway._sse_diagnostics_file_logger.propagate = False
    gateway._sse_diagnostics_file_logger.addHandler(queue_handler)
    gateway._sse_diagnostics_queue = diagnostic_queue
    gateway._sse_diagnostics_queue_handler = queue_handler
    gateway._sse_diagnostics_file_initialized = True
    gateway._sse_diagnostics_file_disabled = False
    gateway._sse_diagnostics_file_warning_emitted = False

    chunks = [b"data: queue-full\n\n", b"data: [DONE]\n\n"]
    upstream_response = FakeUpstreamResponse(chunks)
    service, _ = _service(upstream_response)
    caplog.set_level(logging.WARNING, logger="ombre_brain.gateway")
    started_at = time.perf_counter()
    response = await _raw_openai_response(service)
    output = await _collect(response)
    elapsed = time.perf_counter() - started_at

    assert output == b"".join(chunks)
    assert elapsed < 0.2
    assert diagnostic_queue.qsize() == 1
    warnings = [
        record
        for record in caplog.records
        if "SSE diagnostics file logging warning" in record.getMessage()
    ]
    assert len(warnings) == 1
    assert "queue is full" in warnings[0].getMessage()
    assert gateway._sse_diagnostics_file_disabled is False


async def test_sse_file_write_failure_warns_once_without_affecting_stream(
    caplog,
    monkeypatch,
):
    chunks = [b"data: unchanged\n\n", b"data: [DONE]\n\n"]
    upstream_response = FakeUpstreamResponse(chunks)
    service, _ = _service(upstream_response)
    handler = gateway._sse_diagnostics_file_handler
    assert handler is not None

    def fail_write(record):
        raise OSError("diagnostics disk unavailable")

    monkeypatch.setattr(handler, "shouldRollover", fail_write)
    caplog.set_level(logging.WARNING, logger="ombre_brain.gateway")
    response = await _raw_openai_response(service)

    assert await _collect(response) == b"".join(chunks)
    assert _wait_until(lambda: gateway._sse_diagnostics_file_disabled)
    assert _wait_until(
        lambda: any(
            "SSE diagnostics file logging warning" in record.getMessage()
            for record in caplog.records
        )
    )
    warnings = [
        record
        for record in caplog.records
        if "SSE diagnostics file logging warning" in record.getMessage()
    ]
    assert len(warnings) == 1
    assert gateway._sse_diagnostics_file_disabled is True
    assert upstream_response.closed is True


async def test_sse_file_creation_failure_warns_once_without_affecting_stream(
    caplog,
    monkeypatch,
):
    chunks = [b"data: unchanged\n\n", b"data: [DONE]\n\n"]
    upstream_response = FakeUpstreamResponse(chunks)
    service, _ = _service(upstream_response)
    _reset_sse_diagnostics_file_logger()

    def fail_create(*args, **kwargs):
        raise PermissionError("diagnostics directory is read-only")

    monkeypatch.setattr(gateway, "_BestEffortRotatingFileHandler", fail_create)
    caplog.set_level(logging.WARNING, logger="ombre_brain.gateway")
    gateway._initialize_sse_diagnostics_file_logging()
    response = await _raw_openai_response(service)

    assert await _collect(response) == b"".join(chunks)
    warnings = [
        record
        for record in caplog.records
        if "SSE diagnostics file logging warning" in record.getMessage()
    ]
    assert len(warnings) == 1
    assert gateway._sse_diagnostics_file_handler is None
    assert gateway._sse_diagnostics_file_disabled is True
    assert upstream_response.closed is True


async def test_native_anthropic_stream_bytes_are_unchanged():
    chunks = [
        b'event: content_block_delta\ndata: {"type":"content_block_delta"}\n\n',
        b'event: message_stop\ndata: {"type":"message_stop"}\n\n',
    ]
    upstream_response = FakeUpstreamResponse(chunks)
    service, finalize_calls = _service(upstream_response)

    response = await service._stream_native_anthropic_upstream(
        ROUTE,
        {"model": MODEL, "messages": [{"role": "user", "content": "private"}]},
        SESSION,
        [],
        "private",
    )

    assert await _collect(response) == b"".join(chunks)
    assert upstream_response.closed is True
    assert len(finalize_calls) == 1


class FixedDatetime:
    @classmethod
    def now(cls, tz=None):
        return real_datetime(2026, 7, 18, 12, 34, 56, 123456, tzinfo=timezone.utc)


async def test_openai_to_anthropic_stream_output_remains_exact(monkeypatch):
    upstream_response = FakeUpstreamResponse()
    service, _ = _service(upstream_response)
    monkeypatch.setattr(gateway, "datetime", FixedDatetime)

    response = await service._stream_upstream_as_anthropic(
        {"model": MODEL, "messages": []},
        SESSION,
        [],
        "",
    )

    message_id = "msg_20260718123456123456"
    expected = b"".join(
        [
            service._anthropic_sse(
                "message_start",
                {
                    "type": "message_start",
                    "message": {
                        "id": message_id,
                        "type": "message",
                        "role": "assistant",
                        "model": MODEL,
                        "content": [],
                        "stop_reason": None,
                        "stop_sequence": None,
                        "usage": {"input_tokens": 0, "output_tokens": 0},
                    },
                },
            ),
            service._anthropic_sse(
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                    "usage": {"output_tokens": 0},
                },
            ),
            service._anthropic_sse("message_stop", {"type": "message_stop"}),
        ]
    )
    assert await _collect(response) == expected


async def test_anthropic_to_openai_stream_output_remains_exact(monkeypatch):
    upstream_response = FakeUpstreamResponse()
    service, _ = _service(upstream_response)
    monkeypatch.setattr(gateway, "datetime", FixedDatetime)
    monkeypatch.setattr(gateway.time, "time", lambda: 1_721_305_296)

    response = await service._stream_anthropic_upstream_as_openai(
        ROUTE,
        {"model": MODEL, "messages": []},
        SESSION,
        [],
        "",
    )

    chunk_id = "chatcmpl_20260718123456123456"

    def openai_chunk(delta, finish_reason=None, usage=None):
        body = {
            "id": chunk_id,
            "object": "chat.completion.chunk",
            "created": 1_721_305_296,
            "model": MODEL,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
        }
        if usage is not None:
            body["usage"] = usage
        return service._openai_sse(body)

    expected = b"".join(
        [
            openai_chunk({"role": "assistant"}),
            openai_chunk(
                {},
                "stop",
                service._anthropic_usage_to_openai_usage({}),
            ),
            b"data: [DONE]\n\n",
        ]
    )
    assert await _collect(response) == expected


async def test_upstream_read_exception_is_logged_redacted_and_reraised(
    caplog,
    isolated_sse_file_log,
):
    first_chunk = b"data: partial\n\n"
    read_error = RuntimeError(
        "api_key=TOPSECRET token=TOKENVALUE Bearer BEARERSECRET"
    )
    upstream_response = FakeUpstreamResponse([first_chunk], read_error=read_error)
    service, _ = _service(upstream_response)
    caplog.set_level(logging.ERROR, logger="ombre_brain.gateway")
    response = await _raw_openai_response(service)
    received = []

    with pytest.raises(RuntimeError) as raised:
        async for chunk in response.body_iterator:
            received.append(chunk)

    assert raised.value is read_error
    assert received == [first_chunk]
    assert "stage=upstream_read" in caplog.text
    assert "exception_type=RuntimeError" in caplog.text
    assert "<redacted>" in caplog.text
    assert "TOPSECRET" not in caplog.text
    assert "TOKENVALUE" not in caplog.text
    assert "BEARERSECRET" not in caplog.text
    file_log = _read_log_when_contains(
        isolated_sse_file_log / "sse-stream-diagnostics.log",
        "Gateway SSE stream failed",
    )
    assert "Gateway SSE stream failed" in file_log
    assert "event=failed" in file_log
    assert "stage=upstream_read" in file_log
    assert "exception_type=RuntimeError" in file_log
    assert "TOPSECRET" not in file_log
    assert "TOKENVALUE" not in file_log
    assert "BEARERSECRET" not in file_log
    assert any(
        record.exc_info is not None
        for record in caplog.records
        if "Gateway SSE stream failed" in record.getMessage()
    )


async def test_cancelled_error_is_logged_and_reraised(caplog):
    cancellation = asyncio.CancelledError("client disconnected")
    upstream_response = FakeUpstreamResponse(read_error=cancellation)
    service, _ = _service(upstream_response)
    caplog.set_level(logging.ERROR, logger="ombre_brain.gateway")
    response = await _raw_openai_response(service)

    with pytest.raises(asyncio.CancelledError) as raised:
        await _collect(response)

    assert raised.value is cancellation
    assert "stage=downstream_cancelled" in caplog.text
    assert "exception_type=CancelledError" in caplog.text
    assert upstream_response.closed is True


async def test_finalize_exception_is_logged_with_finalize_stage_and_reraised(caplog):
    finalize_error = ValueError("finalize failed")
    upstream_response = FakeUpstreamResponse([b"data: partial\n\n"])
    service, _ = _service(upstream_response, finalize_error=finalize_error)
    caplog.set_level(logging.ERROR, logger="ombre_brain.gateway")
    response = await _raw_openai_response(service)

    with pytest.raises(ValueError) as raised:
        await _collect(response)

    assert raised.value is finalize_error
    assert "stage=finalize" in caplog.text
    assert "exception_type=ValueError" in caplog.text
    assert "Gateway SSE stream completed" not in caplog.text
    assert upstream_response.closed is True


async def test_upstream_close_exception_is_logged_and_reraised(caplog):
    close_error = OSError("close failed")
    upstream_response = FakeUpstreamResponse(close_error=close_error)
    service, _ = _service(upstream_response)
    caplog.set_level(logging.ERROR, logger="ombre_brain.gateway")
    response = await _raw_openai_response(service)

    with pytest.raises(OSError) as raised:
        await _collect(response)

    assert raised.value is close_error
    assert "stage=upstream_close" in caplog.text
    assert "exception_type=OSError" in caplog.text
