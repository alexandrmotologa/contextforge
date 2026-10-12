"""Unit tests for the semantic token compactor and salience filter."""

import pytest
from contextforge.compaction.base import CompactorContext
from contextforge.compaction.semantic_compactor import SemanticCompactor


def test_semantic_compaction_reduces_tokens():
    long_text = """
The ContextForge system initializes a background daemon for proxying API traffic.
It monitors incoming requests on port 8000 and connects to Ollama on port 11434.
Many services in distributed systems encounter high memory usage when handling large contexts.
Large language models consume substantial GPU memory when generating attention keys and values.
In particular, the KV cache expands linearly with prompt sequence length.
A context of 128,000 tokens can require dozens of gigabytes of VRAM.
ContextForge tackles this bottleneck through intelligent AST pruning and semantic extraction.
By eliminating unneeded tokens prior to model ingestion, TTFT is substantially accelerated.
The prompt processing time decreases because fewer attention matrices need calculation.
Furthermore, memory bandwidth bottlenecks are alleviated during initial prefill.
Users experience lower latency and higher overall system throughput.
"""
    compactor = SemanticCompactor()
    ctx = CompactorContext(
        target_ratio=0.5,
        strategy="balanced",
    )

    result = compactor.compact(long_text, ctx)
    assert result.original_tokens > result.compacted_tokens
    assert result.tokens_saved > 0
    assert result.compression_ratio <= 0.65
    assert result.metadata["semantic_sentences_kept"] > 0


def test_semantic_compactor_query_salience():
    text = """
Section Alpha covers the billing infrastructure and Stripe webhook handlers.
Section Beta explains user onboarding and verification workflows.
Section Gamma details the PostgreSQL database connection pool at host 10.0.0.5 port 5432.
Section Delta outlines the frontend React 19 UI component hierarchy.
Section Epsilon documents the deployment automation scripts using Docker Compose.
"""
    compactor = SemanticCompactor()
    ctx = CompactorContext(
        target_ratio=0.4,
        strategy="balanced",
        query_context="Where is the PostgreSQL database connection configured?",
    )

    result = compactor.compact(text, ctx)
    # The database sentence must be preserved due to high BM25 query salience
    assert "PostgreSQL" in result.compacted_text
    assert "5432" in result.compacted_text


def test_semantic_compactor_deduplicates_repeats():
    text = """
INFO: Starting health check cycle.
STATUS: Worker thread alive.
STATUS: Worker thread alive.
STATUS: Worker thread alive.
STATUS: Worker thread alive.
STATUS: Worker thread alive.
ERROR: Connection to upstream failed at /var/log/err.log.
INFO: Health check completed successfully.
"""
    compactor = SemanticCompactor()
    ctx = CompactorContext(target_ratio=0.5)

    result = compactor.compact(text, ctx)
    assert "[repeated" in result.compacted_text
    assert "Worker thread alive" in result.compacted_text
    assert "/var/log/err.log" in result.compacted_text
