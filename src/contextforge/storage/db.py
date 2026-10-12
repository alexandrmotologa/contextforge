"""Persistent SQLite storage for request metrics, token savings, and proxy telemetry."""

import time
from pathlib import Path
from typing import Any, Dict, List, Optional
import aiosqlite
from contextforge.core.models import CompactionMetadata

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS compaction_records (
    id TEXT PRIMARY KEY,
    timestamp REAL NOT NULL,
    model TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    original_tokens INTEGER NOT NULL,
    compacted_tokens INTEGER NOT NULL,
    tokens_saved INTEGER NOT NULL,
    compression_ratio REAL NOT NULL,
    duration_ms REAL NOT NULL,
    ttft_saved_ms REAL NOT NULL,
    strategy TEXT NOT NULL,
    ast_applied INTEGER NOT NULL,
    kv_prefix_hash TEXT,
    streaming INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_compaction_timestamp ON compaction_records(timestamp);
CREATE INDEX IF NOT EXISTS idx_compaction_model ON compaction_records(model);
"""


class TelemetryDatabase:
    """Async database repository managing historical compaction and latency metrics."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._ensure_parent_dir()

    def _ensure_parent_dir(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    async def initialize(self) -> None:
        """Create tables and indexes if they do not exist."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(CREATE_TABLE_SQL)
            await db.commit()

    async def record_transaction(
        self,
        request_id: str,
        model: str,
        endpoint: str,
        metadata: CompactionMetadata,
        streaming: bool = False,
    ) -> None:
        """Insert a compaction record into the database."""
        query = """
        INSERT OR REPLACE INTO compaction_records (
            id, timestamp, model, endpoint,
            original_tokens, compacted_tokens, tokens_saved,
            compression_ratio, duration_ms, ttft_saved_ms,
            strategy, ast_applied, kv_prefix_hash, streaming
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                query,
                (
                    request_id,
                    time.time(),
                    model,
                    endpoint,
                    metadata.original_tokens,
                    metadata.compacted_tokens,
                    metadata.tokens_saved,
                    metadata.compression_ratio,
                    metadata.duration_ms,
                    metadata.estimated_ttft_saved_ms,
                    metadata.strategy_used,
                    1 if metadata.ast_applied else 0,
                    metadata.kv_prefix_hash,
                    1 if streaming else 0,
                ),
            )
            await db.commit()

    async def get_summary_stats(self) -> Dict[str, Any]:
        """Aggregate cumulative token savings and average performance metrics."""
        query = """
        SELECT
            COUNT(*) as total_requests,
            COALESCE(SUM(original_tokens), 0) as total_original_tokens,
            COALESCE(SUM(compacted_tokens), 0) as total_compacted_tokens,
            COALESCE(SUM(tokens_saved), 0) as total_tokens_saved,
            COALESCE(AVG(compression_ratio), 1.0) as avg_compression_ratio,
            COALESCE(SUM(ttft_saved_ms), 0.0) as total_ttft_saved_ms,
            COALESCE(AVG(duration_ms), 0.0) as avg_overhead_ms
        FROM compaction_records
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return {
                        "total_requests": 0,
                        "total_original_tokens": 0,
                        "total_compacted_tokens": 0,
                        "total_tokens_saved": 0,
                        "avg_compression_ratio": 1.0,
                        "total_ttft_saved_ms": 0.0,
                        "avg_overhead_ms": 0.0,
                    }

                total_orig = row["total_original_tokens"]
                total_saved = row["total_tokens_saved"]
                overall_reduction = (
                    round((total_saved / total_orig) * 100, 1) if total_orig > 0 else 0.0
                )

                return {
                    "total_requests": row["total_requests"],
                    "total_original_tokens": total_orig,
                    "total_compacted_tokens": row["total_compacted_tokens"],
                    "total_tokens_saved": total_saved,
                    "overall_reduction_pct": overall_reduction,
                    "avg_compression_ratio": round(row["avg_compression_ratio"], 4),
                    "total_ttft_saved_seconds": round(row["total_ttft_saved_ms"] / 1000.0, 2),
                    "avg_overhead_ms": round(row["avg_overhead_ms"], 2),
                }

    async def get_recent_records(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieve recent transaction history for dashboard inspection."""
        query = """
        SELECT
            id, timestamp, model, endpoint,
            original_tokens, compacted_tokens, tokens_saved,
            compression_ratio, duration_ms, ttft_saved_ms,
            strategy, ast_applied, kv_prefix_hash, streaming
        FROM compaction_records
        ORDER BY timestamp DESC
        LIMIT ?
        """
        records: List[Dict[str, Any]] = []
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, (limit,)) as cursor:
                async for row in cursor:
                    records.append(dict(row))
        return records
