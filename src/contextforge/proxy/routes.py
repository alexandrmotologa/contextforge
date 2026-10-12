"""API management routes for direct compression, telemetry, and health inspection."""

from typing import Any, Dict, List
from fastapi import APIRouter, Depends, HTTPException, Request
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
        "upstream_reachable": upstream_alive,
    }
