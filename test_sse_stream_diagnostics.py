import asyncio
import logging
from datetime import datetime as real_datetime, timezone

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


async def test_raw_openai_stream_bytes_are_unchanged_and_logs_are_private(caplog, monkeypatch):
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
    for private_value in (
        "PRIVATE_MESSAGE_BODY",
        "PRIVATE_ASSISTANT_BODY",
        "PRIVATE_REASONING_BODY",
        "PRIVATE_PAYLOAD_TOKEN",
        "sk-upstream-private",
    ):
        assert private_value not in caplog.text


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


async def test_upstream_read_exception_is_logged_redacted_and_reraised(caplog):
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
