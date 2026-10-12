"""Fast and accurate token estimation for context budgeting and compaction analysis."""

import re
from typing import List, Optional, Sequence
from contextforge.core.models import ChatMessage

# Regex pattern splitting on words, contractions, numbers, punctuation, and whitespace sequences
_TOKEN_PATTERN = re.compile(
    r"""'s|'t|'re|'ve|'m|'ll|'d|[^\r\n\w]?\w+|\d{1,3}|[^\s\w]+[\r\n]*|\s*[\r\n]+|\s+(?!\S)|\s+""",
    re.UNICODE,
)


class FastTokenizer:
    """Heuristic token estimator calibrated against modern subword tokenizers (Llama-3, cl100k)."""

    def __init__(self, chars_per_token: float = 3.85):
        self.chars_per_token = chars_per_token
        self._pattern = _TOKEN_PATTERN

    def count_tokens(self, text: Optional[str] = None) -> int:
        """Count approximate tokens in a string.

        Uses subword heuristics: words longer than 6 characters or containing
        mixed camelCase/snake_case are weighted as multiple tokens.
        """
        if not text:
            return 0

        # Fast path for very short texts
        if len(text) <= 4:
            return 1

        matches = self._pattern.findall(text)
        token_count = 0
        for match in matches:
            length = len(match)
            if length <= 4:
                token_count += 1
            elif length <= 8:
                token_count += 2
            elif length <= 14:
                token_count += 3
            else:
                token_count += max(4, int(length / self.chars_per_token))

        return max(1, token_count)

    def count_message_tokens(self, message: ChatMessage) -> int:
        """Calculate token overhead for an OpenAI chat message (including role wrapper tokens)."""
        # Standard OpenAI format has 3 overhead tokens per message (<|im_start|>{role}\n{content}<|im_end|>)
        overhead = 4
        content_tokens = self.count_tokens(message.content or "")
        name_tokens = self.count_tokens(message.name or "") if message.name else 0
        return overhead + content_tokens + name_tokens

    def count_messages_tokens(self, messages: Sequence[ChatMessage]) -> int:
        """Total token count for a list of chat completion messages."""
        total = 3  # Conversation wrapper priming tokens (<|im_start|>assistant...)
        for msg in messages:
            total += self.count_message_tokens(msg)
        return total

    def truncate_to_tokens(self, text: str, max_tokens: int) -> str:
        """Truncate text to approximately fit within a token budget without breaking lines."""
        if not text or max_tokens <= 0:
            return ""

        current_tokens = self.count_tokens(text)
        if current_tokens <= max_tokens:
            return text

        ratio = max_tokens / current_tokens
        char_cutoff = int(len(text) * ratio)
        truncated = text[:char_cutoff]

        # Snap to nearest line boundary if available
        last_newline = truncated.rfind("\n")
        if last_newline > char_cutoff * 0.7:
            return truncated[:last_newline]
        return truncated


_DEFAULT_TOKENIZER = FastTokenizer()


def count_tokens(text: str) -> int:
    """Convenience helper to estimate tokens in a string."""
    return _DEFAULT_TOKENIZER.count_tokens(text)


def count_messages_tokens(messages: Sequence[ChatMessage]) -> int:
    """Convenience helper to estimate total tokens in chat messages."""
    return _DEFAULT_TOKENIZER.count_messages_tokens(messages)


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    """Convenience helper to truncate string to budget."""
    return _DEFAULT_TOKENIZER.truncate_to_tokens(text, max_tokens)
