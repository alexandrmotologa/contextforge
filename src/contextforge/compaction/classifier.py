"""Adaptive prompt strategy classifier for automated auto-tuning compaction presets."""

import re
from typing import Dict, List, Literal, Optional, Tuple
from contextforge.core.models import ChatMessage
from contextforge.core.tokenizer import count_tokens

LOG_LINE_REGEX = re.compile(
    r"^(?:\[?\d{4}[-/.]\d{2}[-/.]\d{2}[\sT]\d{2}:\d{2}:\d{2}|INFO|DEBUG|WARN|WARNING|ERROR|FATAL|CRITICAL|TRACE|STATUS):?",
    re.IGNORECASE | re.MULTILINE,
)
CODE_FENCE_REGEX = re.compile(r"```[a-zA-Z0-9_\-\.\+]*\n[\s\S]*?```")


class StrategyClassifier:
    """Analyzes prompt characteristics and automatically selects optimal compaction presets."""

    def classify_text(
        self,
        text: str,
        query_context: Optional[str] = None,
    ) -> Tuple[Literal["balanced", "aggressive", "code_focused", "conservative"], Dict[str, float]]:
        """Classify a text string and return the recommended compaction strategy with metrics."""
        if not text or not text.strip():
            return "conservative", {"code_ratio": 0.0, "log_ratio": 0.0, "tokens": 0.0}

        total_chars = len(text)
        token_count = count_tokens(text)

        # 1. Compute code fence density
        code_blocks = CODE_FENCE_REGEX.findall(text)
        code_chars = sum(len(cb) for cb in code_blocks)
        code_ratio = code_chars / total_chars if total_chars > 0 else 0.0

        # Also check for heavy indentation or python/c syntax if no fences
        if code_ratio < 0.2 and ("def " in text or "function " in text or "class " in text or "import " in text):
            code_ratio = 0.45

        # 2. Compute log / repeated diagnostic density
        lines = text.splitlines()
        total_lines = len(lines)
        log_lines = sum(1 for line in lines if LOG_LINE_REGEX.match(line.strip()))
        log_ratio = log_lines / total_lines if total_lines > 0 else 0.0

        metrics = {
            "code_ratio": round(code_ratio, 3),
            "log_ratio": round(log_ratio, 3),
            "tokens": float(token_count),
        }

        # 3. Decision tree
        if code_ratio >= 0.38:
            return "code_focused", metrics
        elif log_ratio >= 0.25:
            return "aggressive", metrics
        elif token_count < 1200:
            return "conservative", metrics
        else:
            return "balanced", metrics

    def classify_messages(
        self,
        messages: List[ChatMessage],
    ) -> Tuple[Literal["balanced", "aggressive", "code_focused", "conservative"], Dict[str, float]]:
        """Classify a sequence of conversation messages."""
        combined_text = "\n\n".join(m.content or "" for m in messages)
        # Extract potential query from the last user message
        last_user_query = None
        for m in reversed(messages):
            if m.role == "user" and m.content:
                last_user_query = m.content[:200]
                break

        return self.classify_text(combined_text, query_context=last_user_query)
