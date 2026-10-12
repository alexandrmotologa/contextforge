"""Unit tests for configuration, data models, and token counting."""

import pytest
from contextforge.core.config import Settings, get_settings
from contextforge.core.models import (
    ChatMessage,
    ChatCompletionRequest,
    UsageInfo,
    CompactionMetadata,
)
from contextforge.core.tokenizer import count_tokens, count_messages_tokens, truncate_to_tokens


def test_default_settings():
    settings = get_settings()
    assert settings.port == 8000
    assert settings.target_ratio == 0.45
    assert settings.ast_compaction_enabled is True
    assert settings.preserve_recent_turns == 3


def test_chat_message_and_request_models():
    msg = ChatMessage(role="user", content="Hello, test prompt!")
    assert msg.role == "user"
    assert msg.content == "Hello, test prompt!"

    req = ChatCompletionRequest(
        model="llama3:8b",
        messages=[msg],
        compress=True,
        target_ratio=0.5,
    )
    assert req.model == "llama3:8b"
    assert req.compress is True
    assert req.target_ratio == 0.5


def test_tokenizer_counting():
    text = "The quick brown fox jumps over the lazy dog."
    tokens = count_tokens(text)
    assert tokens > 5
    assert tokens < 20

    empty_tokens = count_tokens("")
    assert empty_tokens == 0

    code_sample = """
    def calculate_fibonacci(n: int) -> int:
        if n <= 1:
            return n
        return calculate_fibonacci(n - 1) + calculate_fibonacci(n - 2)
    """
    code_tokens = count_tokens(code_sample)
    assert code_tokens > 15


def test_message_tokens_counting():
    messages = [
        ChatMessage(role="system", content="You are a helpful coding assistant."),
        ChatMessage(role="user", content="Write a quicksort in Python."),
    ]
    total = count_messages_tokens(messages)
    assert total > 15


def test_truncate_to_tokens():
    text = "Line 1\nLine 2\nLine 3\nLine 4\nLine 5\nLine 6\nLine 7\nLine 8"
    truncated = truncate_to_tokens(text, max_tokens=6)
    assert len(truncated) < len(text)
