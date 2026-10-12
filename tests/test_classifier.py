"""Unit tests for the StrategyClassifier auto-tuning preset selector."""

import pytest
from contextforge.compaction.classifier import StrategyClassifier
from contextforge.core.models import ChatMessage


def test_classifier_code_heavy_prompt():
    classifier = StrategyClassifier()
    code_prompt = """
Here is the core logic:
```python
def process_pipeline(items: list) -> list:
    results = []
    for item in items:
        if item.is_valid():
            results.append(item.transform())
    return results

def helper_one():
    return 10
```
Explain this logic.
"""
    strategy, metrics = classifier.classify_text(code_prompt)
    assert strategy == "code_focused"
    assert metrics["code_ratio"] > 0.35


def test_classifier_log_heavy_prompt():
    classifier = StrategyClassifier()
    log_prompt = """
2026-10-12 10:00:01 INFO: Worker starting
2026-10-12 10:00:02 INFO: Initializing connection
2026-10-12 10:00:03 DEBUG: Pool healthy
2026-10-12 10:00:04 ERROR: Connection reset by peer
2026-10-12 10:00:05 WARN: Retrying in 5 seconds
Why did the connection fail?
"""
    strategy, metrics = classifier.classify_text(log_prompt)
    assert strategy == "aggressive"
    assert metrics["log_ratio"] >= 0.25


def test_classifier_short_context():
    classifier = StrategyClassifier()
    short_prompt = "What is the capital of Romania?"
    strategy, metrics = classifier.classify_text(short_prompt)
    assert strategy == "conservative"
    assert metrics["tokens"] < 1200


def test_classifier_classify_messages():
    classifier = StrategyClassifier()
    messages = [
        ChatMessage(role="system", content="You are a system engineer."),
        ChatMessage(role="user", content="Here is the module:\n```python\nclass Service:\n    pass\n```"),
        ChatMessage(role="user", content="How does this work?"),
    ]
    strategy, metrics = classifier.classify_messages(messages)
    assert strategy in ("code_focused", "conservative", "balanced")
