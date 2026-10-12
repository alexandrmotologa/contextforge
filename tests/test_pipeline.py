"""Unit tests for the end-to-end compaction pipeline and KV-cache optimizer."""

import pytest
from contextforge.compaction.kv_optimizer import KvCacheOptimizer
from contextforge.compaction.pipeline import CompactionPipeline
from contextforge.core.config import Settings
from contextforge.core.models import ChatMessage


def test_kv_optimizer_canonical_prefix():
    optimizer = KvCacheOptimizer()
    text = "  System instruction with trailing spaces   \r\n\r\n\r\nSecond line.   "
    canonical = optimizer.canonicalize_prefix(text)
    assert "\r" not in canonical
    assert not canonical.endswith(" ")
    assert "\n\n\n" not in canonical


def test_kv_optimizer_message_partitioning():
    optimizer = KvCacheOptimizer()
    messages = [
        ChatMessage(role="system", content="System instruction 1"),
        ChatMessage(role="system", content="System instruction 2"),
        ChatMessage(role="user", content="Turn 1 user"),
        ChatMessage(role="assistant", content="Turn 1 assistant"),
        ChatMessage(role="user", content="Turn 2 user"),
        ChatMessage(role="assistant", content="Turn 2 assistant"),
        ChatMessage(role="user", content="Turn 3 user query"),
    ]

    prefix, middle, recent, prefix_hash = optimizer.optimize_messages(
        messages, preserve_recent_turns=3
    )
    assert len(prefix) == 2
    assert all(m.role == "system" for m in prefix)
    assert len(recent) == 3
    assert len(prefix_hash) == 16


def test_compaction_pipeline_under_threshold():
    settings = Settings(min_tokens_to_compress=5000)
    pipeline = CompactionPipeline(settings=settings)

    messages = [
        ChatMessage(role="system", content="Be helpful."),
        ChatMessage(role="user", content="What is 2+2?"),
    ]

    compacted_msgs, meta = pipeline.compact_messages(messages)
    assert meta.strategy_used == "bypass_under_threshold"
    assert meta.tokens_saved == 0
    assert len(compacted_msgs) == 2


def test_compaction_pipeline_large_workload():
    # Force low threshold and preserve_recent_turns=1 so middle history triggers compaction
    settings = Settings(min_tokens_to_compress=50, target_ratio=0.45, preserve_recent_turns=1)
    pipeline = CompactionPipeline(settings=settings)

    code_content = """
```python
def process_data(data: list) -> list:
    \"\"\"Process the input dataset line by line.\"\"\"
    cleaned = [d.strip() for d in data if d]
    return cleaned

def helper_one():
    \"\"\"Helper one docstring.\"\"\"
    x = 10
    y = 20
    return x + y

def helper_two():
    \"\"\"Helper two docstring.\"\"\"
    return [i * 2 for i in range(50)]
```

Here are some detailed background explanations about the deployment process:
The server starts up and listens on port 8000.
We have configured standard telemetry monitoring for CPU and memory usage.
Worker threads poll the job queue every 5 seconds for new batch tasks.
System logs are aggregated and sent to the centralized logging cluster.
"""
    messages = [
        ChatMessage(role="system", content="You are a senior systems engineer."),
        ChatMessage(role="user", content=code_content),
        ChatMessage(role="assistant", content="I analyzed the code and architecture."),
        ChatMessage(role="user", content="How does process_data handle whitespace?"),
    ]

    compacted_msgs, meta = pipeline.compact_messages(messages)
    assert meta.original_tokens > meta.compacted_tokens
    assert meta.tokens_saved > 0
    assert meta.estimated_ttft_saved_ms > 0
    assert len(compacted_msgs) == 4
    # The last user turn must be preserved intact
    assert compacted_msgs[-1].content == "How does process_data handle whitespace?"
