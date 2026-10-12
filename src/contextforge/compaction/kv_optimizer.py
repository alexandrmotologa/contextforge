"""KV-cache optimization and prompt prefix canonicalization for local LLM engines."""

import hashlib
import re
from typing import List, Tuple
from contextforge.core.models import ChatMessage


class KvCacheOptimizer:
    """Optimizes prompt structure to maximize KV-cache prefix hits in vLLM, llama.cpp, and Ollama."""

    def __init__(self, attention_sink_tokens: int = 4):
        self.attention_sink_tokens = attention_sink_tokens

    def canonicalize_prefix(self, text: str) -> str:
        """Normalize whitespace, line endings, and indentation for deterministic prefix caching."""
        if not text:
            return ""

        # Normalize line breaks
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")

        # Strip trailing whitespace on each line
        lines = [line.rstrip() for line in normalized.splitlines()]

        # Collapse redundant blank lines
        cleaned_lines: List[str] = []
        blank_count = 0
        for line in lines:
            if not line:
                blank_count += 1
                if blank_count <= 1:
                    cleaned_lines.append("")
            else:
                blank_count = 0
                cleaned_lines.append(line)

        return "\n".join(cleaned_lines).strip()

    def compute_prefix_hash(self, messages: List[ChatMessage]) -> str:
        """Compute SHA-256 fingerprint for the prefix messages to identify KV-cache matches."""
        hasher = hashlib.sha256()
        for msg in messages:
            content = self.canonicalize_prefix(msg.content or "")
            hasher.update(f"{msg.role}:{content}\n".encode("utf-8"))
        return hasher.hexdigest()[:16]

    def optimize_messages(
        self,
        messages: List[ChatMessage],
        preserve_recent_turns: int = 3,
        recent_token_budget: int = 4096,
    ) -> Tuple[List[ChatMessage], List[ChatMessage], List[ChatMessage], str]:
        """Partition messages into canonical static prefix, compressible middle, and preserved tail.

        Respects both turn count and recent_token_budget to prevent massive context overrun.

        Returns:
            (prefix_messages, compressible_messages, recent_messages, prefix_hash)
        """
        if not messages:
            return [], [], [], ""

        prefix_messages: List[ChatMessage] = []
        middle_messages: List[ChatMessage] = []

        # Find static system prompt at start
        start_idx = 0
        while start_idx < len(messages) and messages[start_idx].role == "system":
            sys_msg = messages[start_idx]
            canonical_content = self.canonicalize_prefix(sys_msg.content or "")
            prefix_messages.append(
                ChatMessage(
                    role=sys_msg.role,
                    content=canonical_content,
                    name=sys_msg.name,
                )
            )
            start_idx += 1

        remaining = messages[start_idx:]
        if not remaining:
            prefix_hash = self.compute_prefix_hash(prefix_messages)
            return prefix_messages, [], [], prefix_hash

        # Target number of turns to preserve is preserve_recent_turns
        target_recent_count = min(preserve_recent_turns, len(remaining))

        # Check if the recent turns fit within recent_token_budget (keeping at least 1 turn)
        from contextforge.core.tokenizer import count_tokens

        accumulated_tokens = 0
        actual_recent_count = 0

        for msg in reversed(remaining[-target_recent_count:]):
            msg_tokens = count_tokens(msg.content or "")
            if actual_recent_count >= 1 and (accumulated_tokens + msg_tokens > recent_token_budget):
                break
            accumulated_tokens += msg_tokens
            actual_recent_count += 1

        actual_recent_count = max(1, actual_recent_count)
        split_idx = len(remaining) - actual_recent_count

        middle_messages = remaining[:split_idx]
        recent_messages = remaining[split_idx:]

        prefix_hash = self.compute_prefix_hash(prefix_messages)
        return prefix_messages, middle_messages, recent_messages, prefix_hash

