"""FastAPI reverse proxy gateway for OpenAI-compatible chat completions."""

import json
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict, List, Optional, Set
from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
import httpx
from contextforge.compaction.pipeline import CompactionPipeline
from contextforge.core.config import Settings, get_settings
from contextforge.core.models import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    CompactionMetadata,
)
from contextforge.proxy.metrics import metrics
from contextforge.proxy.routes import router as management_router
from contextforge.storage.db import TelemetryDatabase


async def broadcast_telemetry(app: FastAPI, event: Dict[str, Any]) -> None:
    """Broadcast real-time compaction telemetry event to all connected WebSockets."""
    active_sockets: Set[WebSocket] = getattr(app.state, "active_websockets", set())
    for ws in list(active_sockets):
        try:
            await ws.send_json(event)
        except Exception:
            active_sockets.discard(ws)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan managing database lifecycle and shared HTTP client."""
    settings: Settings = app.state.settings
    db = TelemetryDatabase(db_path=settings.db_path)
    await db.initialize()
    app.state.db = db
    app.state.pipeline = CompactionPipeline(settings=settings)
    app.state.http_client = httpx.AsyncClient(timeout=settings.upstream_timeout)
    app.state.active_websockets = set()

    yield

    await app.state.http_client.aclose()


def get_upstream_candidates(settings: Settings) -> List[str]:
    """Return ordered list of upstream candidate endpoints."""
    candidates = [settings.upstream_url]
    for fb in settings.upstream_fallbacks:
        if fb and fb not in candidates:
            candidates.append(fb)
    return candidates


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
    app.state.active_websockets = set()

    # Include analytics, prometheus, and direct compression routes
    app.include_router(management_router)

    @app.websocket("/ws/telemetry")
    async def websocket_telemetry_endpoint(websocket: WebSocket):
        """Live WebSocket stream broadcasting proxy compaction events."""
        await websocket.accept()
        app.state.active_websockets.add(websocket)
        try:
            db: TelemetryDatabase = app.state.db
            stats = await db.get_summary_stats()
            await websocket.send_json({"event": "init", "stats": stats})
            while True:
                # Keep socket alive and respond to client pings
                data = await websocket.receive_text()
                if data == "ping":
                    await websocket.send_text("pong")
        except WebSocketDisconnect:
            pass
        finally:
            app.state.active_websockets.discard(websocket)

    @app.get("/v1/models")
    async def list_models(request: Request) -> Dict[str, Any]:
        """Forward models query to upstream or return fallback model list."""
        client: httpx.AsyncClient = request.app.state.http_client
        upstream_candidates = get_upstream_candidates(request.app.state.settings)

        for u in upstream_candidates:
            try:
                resp = await client.get(f"{u}/v1/models", timeout=3.0)
                if resp.status_code == 200:
                    return resp.json()
            except Exception:
                continue

        # Fallback response if all upstreams are offline
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
        """Intercept chat completions, compact context, and proxy to upstream with failover."""
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

        candidate_base_urls = get_upstream_candidates(settings)

        # Step 2: Handle streaming vs non-streaming responses
        if req.stream:
            return await _handle_streaming_proxy(
                app=request.app,
                client=client,
                candidate_urls=candidate_base_urls,
                payload=payload,
                request_id=req_id,
                model=req.model,
                metadata=metadata,
                db=db,
            )
        else:
            return await _handle_buffered_proxy(
                app=request.app,
                client=client,
                candidate_urls=candidate_base_urls,
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
    app: FastAPI,
    client: httpx.AsyncClient,
    candidate_urls: List[str],
    payload: Dict[str, Any],
    request_id: str,
    model: str,
    metadata: CompactionMetadata,
    db: TelemetryDatabase,
    start_ts: float,
) -> JSONResponse:
    """Send request to upstream LLM pool with automatic failover, inject metrics, and return response."""
    last_err: Optional[Exception] = None
    failover_occurred = False
    upstream_resp = None

    for idx, base_url in enumerate(candidate_urls):
        url = f"{base_url}/v1/chat/completions"
        if idx > 0:
            failover_occurred = True
        try:
            upstream_resp = await client.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            if upstream_resp.status_code == 200:
                break
            elif upstream_resp.status_code in (502, 503, 504) and idx < len(candidate_urls) - 1:
                continue
            else:
                break
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            last_err = e
            if idx < len(candidate_urls) - 1:
                continue

    if upstream_resp is None:
        raise HTTPException(
            status_code=502,
            detail=f"ContextForge could not connect to upstream LLMs ({', '.join(candidate_urls)}). Error: {str(last_err)}",
        )

    if upstream_resp.status_code != 200:
        return JSONResponse(
            status_code=upstream_resp.status_code,
            content=(
                upstream_resp.json()
                if upstream_resp.headers.get("content-type", "").startswith("application/json")
                else {"error": upstream_resp.text}
            ),
        )

    data = upstream_resp.json()

    # Augment usage statistics with compaction metrics
    if "usage" in data:
        data["usage"]["prompt_tokens_saved"] = metadata.tokens_saved
        data["usage"]["original_prompt_tokens"] = metadata.original_tokens
        data["usage"]["compression_ratio"] = metadata.compression_ratio

    data["contextforge_compaction"] = metadata.model_dump()

    # Record telemetry to DB
    await db.record_transaction(
        request_id=request_id,
        model=model,
        endpoint="/v1/chat/completions",
        metadata=metadata,
        streaming=False,
    )

    # Record to Prometheus metrics
    metrics.record_request(
        model=model,
        original_tokens=metadata.original_tokens,
        tokens_saved=metadata.tokens_saved,
        ttft_saved_seconds=metadata.estimated_ttft_saved_ms / 1000.0,
        failover_occurred=failover_occurred,
    )

    # Broadcast WebSocket update
    duration = round((time.perf_counter() - start_ts) * 1000, 1)
    await broadcast_telemetry(
        app,
        {
            "event": "new_request",
            "record": {
                "id": request_id,
                "model": model,
                "original_tokens": metadata.original_tokens,
                "compacted_tokens": metadata.compacted_tokens,
                "tokens_saved": metadata.tokens_saved,
                "compression_ratio": metadata.compression_ratio,
                "ast_applied": metadata.ast_applied,
                "streaming": False,
                "duration_ms": duration,
            },
        },
    )

    return JSONResponse(content=data)


async def _handle_streaming_proxy(
    app: FastAPI,
    client: httpx.AsyncClient,
    candidate_urls: List[str],
    payload: Dict[str, Any],
    request_id: str,
    model: str,
    metadata: CompactionMetadata,
    db: TelemetryDatabase,
) -> StreamingResponse:
    """Stream SSE response chunks with failover support while tracking TTFT."""

    async def event_generator() -> AsyncGenerator[bytes, None]:
        first_token_received = False
        start_time = time.perf_counter()
        ttft_ms = 0.0
        connected_stream = None
        failover_occurred = False

        for idx, base_url in enumerate(candidate_urls):
            url = f"{base_url}/v1/chat/completions"
            if idx > 0:
                failover_occurred = True
            try:
                stream_ctx = client.stream(
                    "POST",
                    url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                response = await stream_ctx.__aenter__()
                if response.status_code == 200:
                    connected_stream = (stream_ctx, response)
                    break
                else:
                    await stream_ctx.__aexit__(None, None, None)
                    if idx == len(candidate_urls) - 1:
                        yield f"data: {json.dumps({'error': f'Upstream error {response.status_code}'})}\n\n".encode()
                        return
            except Exception:
                if idx == len(candidate_urls) - 1:
                    yield f"data: {json.dumps({'error': 'Connection to all upstreams failed'})}\n\n".encode()
                    return

        if not connected_stream:
            yield f"data: {json.dumps({'error': 'No available upstream runner'})}\n\n".encode()
            return

        stream_ctx, response = connected_stream
        try:
            async for line in response.aiter_lines():
                if line:
                    if not first_token_received and line.startswith("data: "):
                        first_token_received = True
                        ttft_ms = round((time.perf_counter() - start_time) * 1000, 2)
                    yield f"{line}\n\n".encode()
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n".encode()
        finally:
            await stream_ctx.__aexit__(None, None, None)
            # Record telemetry upon stream termination
            await db.record_transaction(
                request_id=request_id,
                model=model,
                endpoint="/v1/chat/completions (stream)",
                metadata=metadata,
                streaming=True,
            )

            metrics.record_request(
                model=model,
                original_tokens=metadata.original_tokens,
                tokens_saved=metadata.tokens_saved,
                ttft_saved_seconds=metadata.estimated_ttft_saved_ms / 1000.0,
                failover_occurred=failover_occurred,
            )

            duration = round((time.perf_counter() - start_time) * 1000, 1)
            await broadcast_telemetry(
                app,
                {
                    "event": "new_request",
                    "record": {
                        "id": request_id,
                        "model": model,
                        "original_tokens": metadata.original_tokens,
                        "compacted_tokens": metadata.compacted_tokens,
                        "tokens_saved": metadata.tokens_saved,
                        "compression_ratio": metadata.compression_ratio,
                        "ast_applied": metadata.ast_applied,
                        "streaming": True,
                        "duration_ms": duration,
                    },
                },
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
