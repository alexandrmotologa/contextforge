"""FastAPI reverse proxy gateway for OpenAI-compatible chat completions."""

import json
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict, Optional
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
import httpx
from contextforge.compaction.pipeline import CompactionPipeline
from contextforge.core.config import Settings, get_settings
from contextforge.core.models import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    CompactionMetadata,
)
from contextforge.proxy.routes import router as management_router
from contextforge.storage.db import TelemetryDatabase


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan managing database lifecycle and shared HTTP client."""
    settings: Settings = app.state.settings
    db = TelemetryDatabase(db_path=settings.db_path)
    await db.initialize()
    app.state.db = db
    app.state.pipeline = CompactionPipeline(settings=settings)
    app.state.http_client = httpx.AsyncClient(timeout=settings.upstream_timeout)

    yield

    await app.state.http_client.aclose()


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    """Factory creating the configured FastAPI proxy application."""
    active_settings = settings or get_settings()

    app = FastAPI(
        title="ContextForge Proxy",
        description="Intelligent long-context compression and KV-cache optimization proxy for local LLMs",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = active_settings

    # Include analytics and direct compression routes
    app.include_router(management_router)

    @app.get("/v1/models")
    async def list_models(request: Request) -> Dict[str, Any]:
        """Forward models query to upstream or return fallback model list."""
        client: httpx.AsyncClient = request.app.state.http_client
        upstream_url = request.app.state.settings.upstream_url

        try:
            resp = await client.get(f"{upstream_url}/v1/models")
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass

        # Fallback response if upstream is offline
        return {
            "object": "list",
            "data": [
                {
                    "id": "contextforge-passthrough",
                    "object": "model",
                    "created": int(time.time()),
                    "owned_by": "contextforge",
                }
            ],
        }

    @app.post("/v1/chat/completions")
    async def chat_completions(
        req: ChatCompletionRequest,
        request: Request,
    ):
        """Intercept chat completions, compact context, and proxy to upstream."""
        pipeline: CompactionPipeline = request.app.state.pipeline
        db: TelemetryDatabase = request.app.state.db
        settings: Settings = request.app.state.settings
        client: httpx.AsyncClient = request.app.state.http_client

        req_id = f"cf-{uuid.uuid4().hex[:12]}"
        start_ts = time.perf_counter()

        # Step 1: Run compaction if requested
        if req.compress:
            compacted_messages, metadata = pipeline.compact_messages(
                messages=req.messages,
                target_ratio=req.target_ratio,
                strategy=req.strategy,
            )
        else:
            compacted_messages = req.messages
            metadata = CompactionMetadata(
                original_tokens=0,
                compacted_tokens=0,
                tokens_saved=0,
                compression_ratio=1.0,
                duration_ms=0.0,
                estimated_ttft_saved_ms=0.0,
                strategy_used="uncompressed",
                ast_applied=False,
            )

        # Build upstream payload
        payload = req.model_dump(exclude={"compress", "target_ratio", "strategy"}, exclude_none=True)
        payload["messages"] = [m.model_dump(exclude_none=True) for m in compacted_messages]

        upstream_endpoint = f"{settings.upstream_url}/v1/chat/completions"

        # Step 2: Handle streaming vs non-streaming responses
        if req.stream:
            return await _handle_streaming_proxy(
                client=client,
                upstream_url=upstream_endpoint,
                payload=payload,
                request_id=req_id,
                model=req.model,
                metadata=metadata,
                db=db,
            )
        else:
            return await _handle_buffered_proxy(
                client=client,
                upstream_url=upstream_endpoint,
                payload=payload,
                request_id=req_id,
                model=req.model,
                metadata=metadata,
                db=db,
                start_ts=start_ts,
            )

    @app.get("/", response_class=HTMLResponse)
    @app.get("/dashboard", response_class=HTMLResponse)
    async def dashboard_view(request: Request) -> HTMLResponse:
        """Serve the embedded modern dark-mode dashboard."""
        from contextforge.web.dashboard import get_dashboard_html

        db: TelemetryDatabase = request.app.state.db
        settings: Settings = request.app.state.settings
        stats = await db.get_summary_stats()
        recent = await db.get_recent_records(limit=15)
        html = get_dashboard_html(stats=stats, recent=recent, settings=settings)
        return HTMLResponse(content=html)

    return app


async def _handle_buffered_proxy(
    client: httpx.AsyncClient,
    upstream_url: str,
    payload: Dict[str, Any],
    request_id: str,
    model: str,
    metadata: CompactionMetadata,
    db: TelemetryDatabase,
    start_ts: float,
) -> JSONResponse:
    """Send request to upstream LLM, inject compaction metrics, and return response."""
    try:
        upstream_resp = await client.post(
            upstream_url,
            json=payload,
            headers={"Content-Type": "application/json"},
        )
    except httpx.ConnectError:
        raise HTTPException(
            status_code=502,
            detail=f"ContextForge could not connect to upstream LLM at {upstream_url}. Is your local runner (Ollama / vLLM / llama.cpp) running?",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upstream proxy error: {str(e)}")

    if upstream_resp.status_code != 200:
        return JSONResponse(
            status_code=upstream_resp.status_code,
            content=upstream_resp.json() if upstream_resp.headers.get("content-type", "").startswith("application/json") else {"error": upstream_resp.text},
        )

    data = upstream_resp.json()

    # Augment usage statistics with compaction metrics
    if "usage" in data:
        data["usage"]["prompt_tokens_saved"] = metadata.tokens_saved
        data["usage"]["original_prompt_tokens"] = metadata.original_tokens
        data["usage"]["compression_ratio"] = metadata.compression_ratio

    data["contextforge_compaction"] = metadata.model_dump()

    # Record telemetry
    await db.record_transaction(
        request_id=request_id,
        model=model,
        endpoint="/v1/chat/completions",
        metadata=metadata,
        streaming=False,
    )

    return JSONResponse(content=data)


async def _handle_streaming_proxy(
    client: httpx.AsyncClient,
    upstream_url: str,
    payload: Dict[str, Any],
    request_id: str,
    model: str,
    metadata: CompactionMetadata,
    db: TelemetryDatabase,
) -> StreamingResponse:
    """Stream SSE response chunks directly from upstream to client while tracking TTFT."""

    async def event_generator() -> AsyncGenerator[bytes, None]:
        first_token_received = False
        start_time = time.perf_counter()
        ttft_ms = 0.0

        try:
            async with client.stream(
                "POST",
                upstream_url,
                json=payload,
                headers={"Content-Type": "application/json"},
            ) as response:
                if response.status_code != 200:
                    err_body = await response.aread()
                    yield f"data: {json.dumps({'error': err_body.decode()})}\n\n".encode()
                    return

                async for line in response.aiter_lines():
                    if line:
                        if not first_token_received and line.startswith("data: "):
                            first_token_received = True
                            ttft_ms = round((time.perf_counter() - start_time) * 1000, 2)
                        yield f"{line}\n\n".encode()

        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n".encode()
        finally:
            # Record telemetry upon stream termination
            await db.record_transaction(
                request_id=request_id,
                model=model,
                endpoint="/v1/chat/completions (stream)",
                metadata=metadata,
                streaming=True,
            )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-ContextForge-Saved-Tokens": str(metadata.tokens_saved),
            "X-ContextForge-Compression-Ratio": str(metadata.compression_ratio),
        },
    )
