"""Unit and integration tests for advanced proxy features: Prometheus, failover pool, warming, and exports."""

import pytest
from httpx import ASGITransport, AsyncClient
import httpx
from contextforge.core.config import Settings
from contextforge.proxy.gateway import create_app


@pytest.fixture
def advanced_app(tmp_path):
    db_file = tmp_path / "test_adv.db"
    settings = Settings(
        db_path=db_file,
        upstream_url="http://primary:11434",
        upstream_fallbacks=["http://fallback:11434"],
        min_tokens_to_compress=20,
        prometheus_enabled=True,
    )
    return create_app(settings=settings)


@pytest.mark.asyncio
async def test_prometheus_metrics_endpoint(advanced_app):
    async with advanced_app.router.lifespan_context(advanced_app):
        transport = ASGITransport(app=advanced_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get("/metrics")
            assert res.status_code == 200
            assert "contextforge_requests_total" in res.text
            assert "contextforge_tokens_saved_total" in res.text


@pytest.mark.asyncio
async def test_api_export_json_and_csv(advanced_app):
    async with advanced_app.router.lifespan_context(advanced_app):
        # Insert a sample record
        db = advanced_app.state.db
        from contextforge.core.models import CompactionMetadata
        meta = CompactionMetadata(
            original_tokens=500,
            compacted_tokens=200,
            tokens_saved=300,
            compression_ratio=0.4,
            duration_ms=5.0,
            estimated_ttft_saved_ms=800.0,
            strategy_used="auto",
            ast_applied=True,
        )
        await db.record_transaction("req-exp-1", "llama3", "/v1/chat/completions", meta, streaming=False)

        transport = ASGITransport(app=advanced_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Test JSON export
            json_res = await client.get("/api/export?format=json")
            assert json_res.status_code == 200
            data = json_res.json()
            assert len(data) >= 1
            assert data[0]["id"] == "req-exp-1"

            # Test CSV export
            csv_res = await client.get("/api/export?format=csv")
            assert csv_res.status_code == 200
            assert "text/csv" in csv_res.headers.get("content-type", "")
            assert "req-exp-1" in csv_res.text
            assert "original_tokens" in csv_res.text


@pytest.mark.asyncio
async def test_api_warm_cache_endpoint(advanced_app):
    def mock_warm_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": ""}}]})

    async with advanced_app.router.lifespan_context(advanced_app):
        advanced_app.state.http_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_warm_handler))
        transport = ASGITransport(app=advanced_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.post("/api/warm", json={"content": "System prompt prefix to cache"})
            assert res.status_code == 200
            data = res.json()
            assert data["status"] == "warmed"
            assert "prefix_hash" in data


@pytest.mark.asyncio
async def test_upstream_failover_pool(advanced_app):
    # Primary fails with ConnectionRefused, fallback succeeds
    def mock_failover_handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if "primary" in url_str:
            raise httpx.ConnectError("Primary offline")
        elif "fallback" in url_str:
            return httpx.Response(
                200,
                json={
                    "id": "chatcmpl-fb1",
                    "model": "llama3",
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": "Recovered via fallback"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 50, "completion_tokens": 5, "total_tokens": 55},
                },
            )
        return httpx.Response(500, json={"error": "unknown"})

    async with advanced_app.router.lifespan_context(advanced_app):
        advanced_app.state.http_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_failover_handler))
        transport = ASGITransport(app=advanced_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            payload = {
                "model": "llama3",
                "messages": [{"role": "user", "content": "Hello via failover"}],
                "stream": False,
                "strategy": "auto",
            }
            res = await client.post("/v1/chat/completions", json=payload)
            assert res.status_code == 200
            data = res.json()
            assert data["choices"][0]["message"]["content"] == "Recovered via fallback"
