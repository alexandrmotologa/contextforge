"""Unit tests for SQLite telemetry storage repository."""

import pytest
from pathlib import Path
from contextforge.core.models import CompactionMetadata
from contextforge.storage.db import TelemetryDatabase


@pytest.mark.asyncio
async def test_telemetry_database_lifecycle(tmp_path: Path):
    db_file = tmp_path / "test_telemetry.db"
    db = TelemetryDatabase(db_path=db_file)
    await db.initialize()

    # Verify empty stats
    stats = await db.get_summary_stats()
    assert stats["total_requests"] == 0

    # Insert a sample compaction record
    meta = CompactionMetadata(
        original_tokens=2048,
        compacted_tokens=820,
        tokens_saved=1228,
        compression_ratio=0.4004,
        duration_ms=4.5,
        estimated_ttft_saved_ms=3500.0,
        strategy_used="balanced",
        ast_applied=True,
        kv_prefix_hash="abcd1234efgh5678",
    )

    await db.record_transaction(
        request_id="req-123",
        model="llama3:8b",
        endpoint="/v1/chat/completions",
        metadata=meta,
        streaming=False,
    )

    # Check updated stats
    stats2 = await db.get_summary_stats()
    assert stats2["total_requests"] == 1
    assert stats2["total_original_tokens"] == 2048
    assert stats2["total_tokens_saved"] == 1228
    assert stats2["overall_reduction_pct"] > 50

    # Check recent records
    recent = await db.get_recent_records(limit=10)
    assert len(recent) == 1
    assert recent[0]["id"] == "req-123"
    assert recent[0]["model"] == "llama3:8b"
