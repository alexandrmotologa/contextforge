"""API management routes for direct compression, telemetry, and health inspection."""

from typing import Any, Dict, List
from fastapi import APIRouter, Depends, HTTPException, Request, Response
import httpx
from contextforge.compaction.pipeline import CompactionPipeline
from contextforge.core.config import Settings
from contextforge.core.models import CompressRequest, CompressResponse
from contextforge.storage.db import TelemetryDatabase

router = APIRouter()


def get_pipeline(request: Request) -> CompactionPipeline:
    return request.app.state.pipeline


def get_db(request: Request) -> TelemetryDatabase:
    return request.app.state.db


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


@router.post("/api/compress", response_model=CompressResponse)
async def compress_endpoint(
    req: CompressRequest,
    pipeline: CompactionPipeline = Depends(get_pipeline),
    db: TelemetryDatabase = Depends(get_db),
) -> CompressResponse:
    """Directly compact a prompt or code document without sending to an LLM."""
    compacted, metadata = pipeline.compact_text(
        text=req.content,
        target_ratio=req.target_ratio,
        strategy=req.strategy,
        query_context=req.query_context,
    )

    # Record telemetry
    await db.record_transaction(
        request_id=f"direct-{int(metadata.duration_ms * 1000)}",
        model="direct-compaction",
        endpoint="/api/compress",
        metadata=metadata,
        streaming=False,
    )

    return CompressResponse(compacted_content=compacted, metadata=metadata)


@router.get("/api/stats")
async def stats_endpoint(
    db: TelemetryDatabase = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Dict[str, Any]:
    """Retrieve cumulative token savings and performance telemetry."""
    stats = await db.get_summary_stats()
    return {
        "status": "healthy",
        "upstream_url": settings.upstream_url,
        "default_strategy": settings.default_strategy,
        "target_ratio": settings.target_ratio,
        "telemetry": stats,
    }


@router.get("/api/history")
async def history_endpoint(
    limit: int = 50,
    db: TelemetryDatabase = Depends(get_db),
) -> List[Dict[str, Any]]:
    """Retrieve recent compaction transactions."""
    return await db.get_recent_records(limit=min(limit, 200))


@router.get("/health")
async def health_endpoint(
    settings: Settings = Depends(get_settings),
) -> Dict[str, Any]:
    """Health check validating proxy state and pinging upstream LLM service."""
    upstream_alive = False
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{settings.upstream_url}/health")
            if resp.status_code in (200, 404):
                upstream_alive = True
    except Exception:
        upstream_alive = False

    return {
        "status": "online",
        "service": "ContextForge",
        "version": "0.1.0",
        "upstream_url": settings.upstream_url,
        "upstream_fallbacks": settings.upstream_fallbacks,
        "upstream_reachable": upstream_alive,
    }


@router.get("/metrics")
async def prometheus_metrics_endpoint(
    settings: Settings = Depends(get_settings),
) -> Response:
    """Expose Prometheus plain-text telemetry metrics."""
    if not settings.prometheus_enabled:
        raise HTTPException(status_code=404, detail="Prometheus metrics disabled")
    from fastapi.responses import Response
    from contextforge.proxy.metrics import metrics

    return Response(
        content=metrics.generate_metrics_text(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@router.post("/api/warm")
async def warm_cache_endpoint(
    request: Request,
    pipeline: CompactionPipeline = Depends(get_pipeline),
    settings: Settings = Depends(get_settings),
) -> Dict[str, Any]:
    """Proactively warm upstream KV-cache for a given prompt prefix."""
    body = await request.json()
    content = body.get("content", "")
    from contextforge.core.models import ChatMessage

    prefix_hash = pipeline.kv_optimizer.compute_prefix_hash(
        [ChatMessage(role="system", content=content)]
    )
    client: httpx.AsyncClient = request.app.state.http_client

    upstream_url = f"{settings.upstream_url}/v1/chat/completions"
    warmed = False
    try:
        resp = await client.post(
            upstream_url,
            json={
                "model": body.get("model", "llama3"),
                "messages": [
                    {
                        "role": "system",
                        "content": pipeline.kv_optimizer.canonicalize_prefix(content),
                    }
                ],
                "max_tokens": 1,
            },
            timeout=5.0,
        )
        if resp.status_code == 200:
            warmed = True
    except Exception:
        warmed = False

    return {
        "status": "warmed" if warmed else "bypassed",
        "prefix_hash": prefix_hash,
        "upstream": settings.upstream_url,
    }


@router.get("/api/export")
async def export_telemetry_endpoint(
    format: str = "json",
    db: TelemetryDatabase = Depends(get_db),
) -> Any:
    """Export cumulative compaction telemetry in JSON or CSV format."""
    records = await db.get_recent_records(limit=1000)
    if format.lower() == "csv":
        import csv
        import io
        from fastapi.responses import Response

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "id",
                "timestamp",
                "model",
                "endpoint",
                "original_tokens",
                "compacted_tokens",
                "compression_ratio",
                "duration_ms",
                "streaming",
            ]
        )
        for r in records:
            writer.writerow(
                [
                    r.get("id"),
                    r.get("timestamp"),
                    r.get("model"),
                    r.get("endpoint"),
                    r.get("original_tokens"),
                    r.get("compacted_tokens"),
                    r.get("compression_ratio"),
                    r.get("duration_ms"),
                    r.get("streaming"),
                ]
            )
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=contextforge_telemetry.csv"},
        )

    return records

