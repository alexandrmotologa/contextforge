"""Rich command-line interface for ContextForge powered by Typer and Rich."""

import asyncio
from pathlib import Path
from typing import Optional
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from contextforge.compaction.pipeline import CompactionPipeline
from contextforge.core.config import Settings, get_settings
from contextforge.storage.db import TelemetryDatabase

app = typer.Typer(
    name="contextforge",
    help="ContextForge: Intelligent long-context compression and KV-cache optimization proxy for local LLMs.",
    add_completion=False,
)
console = Console()


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", "--host", "-h", help="Host interface to bind the proxy"),
    port: int = typer.Option(8000, "--port", "-p", help="Port to listen for incoming requests"),
    upstream: str = typer.Option(
        "http://localhost:11434", "--upstream", "-u", help="Upstream LLM server URL (Ollama, vLLM, LM Studio)"
    ),
    ratio: float = typer.Option(0.45, "--ratio", "-r", help="Target token compression ratio (0.1 to 0.9)"),
    strategy: str = typer.Option(
        "balanced", "--strategy", "-s", help="Default compaction strategy: balanced, aggressive, code_focused, conservative"
    ),
    db: str = typer.Option("data/contextforge.db", "--db", help="Path to SQLite metrics database"),
):
    """Start the ContextForge OpenAI-compatible proxy server and Web Dashboard."""
    import uvicorn
    from contextforge.proxy.gateway import create_app

    settings = Settings(
        host=host,
        port=port,
        upstream_url=upstream,
        target_ratio=ratio,
        default_strategy=strategy,
        db_path=Path(db),
    )

    console.print(
        Panel(
            f"[bold cyan]ContextForge Proxy Gateway[/bold cyan]\n"
            f"[dim]Intelligent KV-cache & prompt compression engine[/dim]\n\n"
            f"[bold]Listening on:[/bold] http://{host}:{port}\n"
            f"[bold]Upstream LLM:[/bold] {upstream}\n"
            f"[bold]Target Ratio:[/bold] {ratio * 100:.0f}%\n"
            f"[bold]Strategy:[/bold] {strategy}\n"
            f"[bold]Web Dashboard:[/bold] http://localhost:{port}/dashboard\n"
            f"[bold]OpenAI Endpoint:[/bold] http://localhost:{port}/v1/chat/completions",
            title="ContextForge Daemon",
            border_style="cyan",
        )
    )

    proxy_app = create_app(settings=settings)
    uvicorn.run(proxy_app, host=host, port=port, log_level="info")


@app.command()
def compress(
    input_source: str = typer.Argument(..., help="Path to file or raw text to compress"),
    strategy: str = typer.Option("balanced", "--strategy", "-s", help="Compaction preset"),
    ratio: float = typer.Option(0.45, "--ratio", "-r", help="Target token ratio"),
    query: Optional[str] = typer.Option(None, "--query", "-q", help="Active query context for guided salience"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="File to write compacted content to"),
):
    """Compress a prompt, document, or code file using AST and semantic compaction."""
    # Check if input is a valid file path
    input_path = Path(input_source)
    if input_path.exists() and input_path.is_file():
        content = input_path.read_text(encoding="utf-8")
        console.print(f"[dim]Read {len(content)} characters from file: {input_source}[/dim]")
    else:
        content = input_source

    pipeline = CompactionPipeline()
    compacted, meta = pipeline.compact_text(
        text=content,
        target_ratio=ratio,
        strategy=strategy,
        query_context=query,
    )

    # Render summary table
    table = Table(title="ContextForge Compaction Results", border_style="cyan")
    table.add_column("Metric", style="bold white")
    table.add_column("Value", style="cyan")

    table.add_row("Original Tokens", f"{meta.original_tokens:,}")
    table.add_row("Compacted Tokens", f"{meta.compacted_tokens:,}")
    table.add_row("Tokens Saved", f"{meta.tokens_saved:,} (-{round((1 - meta.compression_ratio) * 100, 1)}%)")
    table.add_row("Duration", f"{meta.duration_ms} ms")
    table.add_row("Estimated TTFT Saved", f"~{meta.estimated_ttft_saved_ms} ms")
    table.add_row("AST Applied", str(meta.ast_applied))
    table.add_row("Strategy Used", meta.strategy_used)

    console.print(table)

    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(compacted, encoding="utf-8")
        console.print(f"[green]✓ Compacted text written to {output}[/green]")
    else:
        console.print("\n[bold cyan]--- Compacted Output ---[/bold cyan]")
        console.print(compacted)


@app.command()
def benchmark(
    sample_size: int = typer.Option(1000, "--tokens", "-t", help="Approximate sample size in tokens"),
):
    """Benchmark all 4 compaction presets on representative long context."""
    pipeline = CompactionPipeline()

    synthetic_code = """
import os
import sys
from typing import Dict, List, Optional

class DataPipelineManager:
    \"\"\"Manages distributed data ingestion streams across worker nodes.\"\"\"
    def __init__(self, node_id: str):
        self.node_id = node_id
        self.buffer = []

    def handle_ingest(self, record: dict) -> bool:
        \"\"\"Core ingestion method parsing incoming records.\"\"\"
        if not record:
            return False
        self.buffer.append(record)
        return True

    def _internal_crypto_hash_calc(self, data: bytes) -> str:
        \"\"\"Internal crypto helper.\"\"\"
        import hashlib
        return hashlib.sha256(data).hexdigest()

    def _flush_buffer_to_disk(self):
        \"\"\"Flush in-memory items.\"\"\"
        self.buffer.clear()
"""
    synthetic_docs = (
        "Distributed database replication relies on write-ahead logs to maintain consensus.\n"
        "Nodes periodically send heartbeat pings across the internal cluster network on port 9092.\n"
        "When a network partition is detected, the quorum election procedure is initiated.\n"
        "All changes must be committed by a majority of voters before acknowledging client requests.\n"
    ) * 12

    benchmark_text = f"```python\n{synthetic_code}\n```\n\n{synthetic_docs}"

    presets = [
        ("balanced", 0.45),
        ("aggressive", 0.25),
        ("code_focused", 0.35),
        ("conservative", 0.65),
    ]
    table = Table(title="ContextForge Preset Benchmarks", border_style="cyan")
    table.add_column("Preset", style="bold", min_width=13)
    table.add_column("Original", justify="right")
    table.add_column("Compacted", justify="right")
    table.add_column("Reduction %", justify="right", style="bold green")
    table.add_column("Latency (ms)", justify="right")
    table.add_column("Est. TTFT Saved", justify="right", style="bold yellow")

    for s, ratio in presets:
        _, meta = pipeline.compact_text(benchmark_text, strategy=s, target_ratio=ratio)
        reduction = round((1.0 - meta.compression_ratio) * 100, 1)
        table.add_row(
            s.replace("_", " ").title(),
            f"{meta.original_tokens:,}",
            f"{meta.compacted_tokens:,}",
            f"-{reduction}%",
            f"{meta.duration_ms} ms",
            f"~{meta.estimated_ttft_saved_ms} ms",
        )

    console.print(table)


@app.command()
def stats(
    db_path: str = typer.Option("data/contextforge.db", "--db", help="Path to database"),
):
    """Display cumulative proxy token savings and performance statistics."""
    db = TelemetryDatabase(db_path=Path(db_path))

    async def _fetch():
        await db.initialize()
        return await db.get_summary_stats()

    data = asyncio.run(_fetch())

    table = Table(title="ContextForge Lifetime Statistics", border_style="cyan")
    table.add_column("Metric", style="bold white")
    table.add_column("Value", style="cyan")

    table.add_row("Total Proxied Requests", f"{data['total_requests']:,}")
    table.add_row("Total Input Tokens", f"{data['total_original_tokens']:,}")
    table.add_row("Total Compacted Tokens", f"{data['total_compacted_tokens']:,}")
    table.add_row("Total Tokens Saved", f"{data['total_tokens_saved']:,}")
    table.add_row("Overall Reduction", f"{data['overall_reduction_pct']}%")
    table.add_row("Average Compression Ratio", f"{data['avg_compression_ratio']:.2f}x")
    table.add_row("Total TTFT Time Saved", f"{data['total_ttft_saved_seconds']} seconds")
    table.add_row("Avg Compaction Overhead", f"{data['avg_overhead_ms']} ms")

    console.print(table)


if __name__ == "__main__":
    app()
