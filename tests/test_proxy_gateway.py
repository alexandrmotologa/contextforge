"""Unit tests for the FastAPI proxy gateway and API endpoints."""

import pytest
from httpx import ASGITransport, AsyncClient
from contextforge.core.config import Settings
from contextforge.proxy.gateway import create_app


@pytest.fixture
def test_app(tmp_path):
    db_file = tmp_path / "test_gateway.db"
    settings = Settings(
        db_path=db_file,
        upstream_url="http://127.0.0.1:19999",
        min_tokens_to_compress=20,
    )
    return create_app(settings=settings)


@pytest.mark.asyncio
async def test_health_endpoint(test_app):
    async with test_app.router.lifespan_context(test_app):
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get("/health")
            assert res.status_code == 200
            data = res.json()
            assert data["status"] == "online"
            assert data["service"] == "ContextForge"


@pytest.mark.asyncio
async def test_direct_compress_endpoint(test_app):
    async with test_app.router.lifespan_context(test_app):
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            payload = {
                "content": """
def helper_func():
    \"\"\"This is a verbose docstring.\"\"\"
    a = 1
    b = 2
    return a + b

def main_func():
    return helper_func()
""",
                "strategy": "aggressive",
                "target_ratio": 0.5,
                "query_context": "How does main_func run?",
            }
            res = await client.post("/api/compress", json=payload)
            assert res.status_code == 200
            data = res.json()
            assert "compacted_content" in data
            assert data["metadata"]["tokens_saved"] >= 0

            # Verify stats reflect the compaction
            stats_res = await client.get("/api/stats")
            assert stats_res.status_code == 200
            stats_data = stats_res.json()
            assert stats_data["telemetry"]["total_requests"] >= 1


@pytest.mark.asyncio
async def test_dashboard_endpoint(test_app):
    async with test_app.router.lifespan_context(test_app):
        # Insert a record so dashboard table has rendered rows
        db = test_app.state.db
        from contextforge.core.models import CompactionMetadata
        meta = CompactionMetadata(
            original_tokens=1000,
            compacted_tokens=400,
            tokens_saved=600,
            compression_ratio=0.4,
            duration_ms=10.0,
            estimated_ttft_saved_ms=1500.0,
            strategy_used="balanced",
            ast_applied=True,
        )
        await db.record_transaction("req-test-dash", "llama3", "/v1/chat/completions", meta, streaming=False)
        await db.record_transaction("req-test-stream", "llama3", "/v1/chat/completions", meta, streaming=True)

        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get("/")
            assert res.status_code == 200
            assert "ContextForge" in res.text
            assert "Tokens Saved" in res.text
            assert "req-test-das" in res.text

            history_res = await client.get("/api/history?limit=10")
            assert history_res.status_code == 200
            assert len(history_res.json()) >= 2


@pytest.mark.asyncio
async def test_v1_models_endpoint(test_app):
    import httpx

    # Mock handler that returns upstream models
    def mock_models_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "object": "list",
                "data": [{"id": "llama3:8b", "object": "model", "created": 123456789, "owned_by": "ollama"}],
            },
        )

    async with test_app.router.lifespan_context(test_app):
        test_app.state.http_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_models_handler))
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get("/v1/models")
            assert res.status_code == 200
            data = res.json()
            assert data["data"][0]["id"] == "llama3:8b"


@pytest.mark.asyncio
async def test_v1_models_fallback_when_upstream_down(test_app):
    import httpx

    def mock_err_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")

    async with test_app.router.lifespan_context(test_app):
        test_app.state.http_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_err_handler))
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get("/v1/models")
            assert res.status_code == 200
            data = res.json()
            assert data["data"][0]["id"] == "contextforge-passthrough"


@pytest.mark.asyncio
async def test_chat_completions_buffered(test_app):
    import httpx

    def mock_chat_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-mock123",
                "object": "chat.completion",
                "created": 123456,
                "model": "llama3",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hello world!"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110},
            },
        )

    async with test_app.router.lifespan_context(test_app):
        test_app.state.http_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_chat_handler))
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            payload = {
                "model": "llama3",
                "messages": [
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": "Write a python function to compute factorial and explain its complexity in detail with examples."},
                ],
                "stream": False,
                "compress": True,
            }
            res = await client.post("/v1/chat/completions", json=payload)
            assert res.status_code == 200
            data = res.json()
            assert data["choices"][0]["message"]["content"] == "Hello world!"
            assert "contextforge_compaction" in data
            assert "prompt_tokens_saved" in data["usage"]


@pytest.mark.asyncio
async def test_chat_completions_streaming(test_app):
    import httpx

    sse_lines = [
        b'data: {"id":"chatcmpl-1","choices":[{"delta":{"content":"Hi"}}]}\n\n',
        b'data: {"id":"chatcmpl-1","choices":[{"delta":{"content":" there"}}]}\n\n',
        b'data: [DONE]\n\n',
    ]

    def mock_sse_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=b"".join(sse_lines),
        )

    async with test_app.router.lifespan_context(test_app):
        test_app.state.http_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_sse_handler))
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            payload = {
                "model": "llama3",
                "messages": [
                    {"role": "system", "content": "You are an assistant."},
                    {"role": "user", "content": "Hello!"},
                ],
                "stream": True,
                "compress": True,
            }
            res = await client.post("/v1/chat/completions", json=payload)
            assert res.status_code == 200
            assert "text/event-stream" in res.headers.get("content-type", "")
            assert "X-ContextForge-Saved-Tokens" in res.headers
            body_text = res.text
            assert "Hi there" in body_text or "chatcmpl-1" in body_text


@pytest.mark.asyncio
async def test_chat_completions_upstream_connection_error(test_app):
    import httpx

    def mock_err_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")

    async with test_app.router.lifespan_context(test_app):
        test_app.state.http_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_err_handler))
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            payload = {
                "model": "llama3",
                "messages": [{"role": "user", "content": "Ping"}],
                "stream": False,
            }
            res = await client.post("/v1/chat/completions", json=payload)
            assert res.status_code == 502
            assert "could not connect" in res.json()["detail"]
