"""End-to-end compaction pipeline orchestrating AST pruning, semantic compaction, and KV caching."""

import time
from typing import List, Optional, Tuple
from contextforge.compaction.ast_compactor import AstCompactor
from contextforge.compaction.base import CompactorContext
from contextforge.compaction.kv_optimizer import KvCacheOptimizer
from contextforge.compaction.semantic_compactor import SemanticCompactor
from contextforge.core.config import Settings, get_settings
from contextforge.core.models import (
    AstSummary,
    ChatMessage,
    CompactionMetadata,
)
from contextforge.core.tokenizer import count_messages_tokens, count_tokens


class CompactionPipeline:
    """Orchestrates multi-stage compaction on chat messages and text prompts."""

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.ast_compactor = AstCompactor()
        self.semantic_compactor = SemanticCompactor()
        self.kv_optimizer = KvCacheOptimizer(
            attention_sink_tokens=self.settings.attention_sink_tokens
        )

    def compact_messages(
        self,
        messages: List[ChatMessage],
        target_ratio: Optional[float] = None,
        strategy: Optional[str] = None,
    ) -> Tuple[List[ChatMessage], CompactionMetadata]:
        """Compact a conversation's messages while protecting system instructions and recent turns."""
        start_time = time.perf_counter()
        original_tokens = count_messages_tokens(messages)

        active_ratio = target_ratio or self.settings.target_ratio
        active_strategy = strategy or self.settings.default_strategy

        # If below threshold, pass through with zero modification
        if original_tokens < self.settings.min_tokens_to_compress:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            meta = CompactionMetadata(
                original_tokens=original_tokens,
                compacted_tokens=original_tokens,
                tokens_saved=0,
                compression_ratio=1.0,
                duration_ms=duration_ms,
                estimated_ttft_saved_ms=0.0,
                strategy_used="bypass_under_threshold",
                ast_applied=False,
            )
            return messages, meta

        # Partition messages into prefix, middle (compressible), and recent tail
        prefix_msgs, middle_msgs, recent_msgs, prefix_hash = self.kv_optimizer.optimize_messages(
            messages,
            preserve_recent_turns=self.settings.preserve_recent_turns,
        )

        # Extract active query context from the most recent user message
        query_context = ""
        for msg in reversed(messages):
            if msg.role == "user" and msg.content:
                query_context = msg.content
                break

        ctx = CompactorContext(
            target_ratio=active_ratio,
            strategy=active_strategy,
            query_context=query_context,
        )

        all_ast_summaries: List[AstSummary] = []
        compacted_middle: List[ChatMessage] = []
        total_kept_sentences = 0
        total_dropped_sentences = 0
        ast_applied_any = False

        for msg in middle_msgs:
            if not msg.content:
                compacted_middle.append(msg)
                continue

            content = msg.content

            # Stage 1: AST Code Compaction on code blocks
            if self.settings.ast_compaction_enabled:
                ast_res = self.ast_compactor.compact(content, ctx)
                content = ast_res.compacted_text
                if ast_res.metadata.get("ast_applied"):
                    ast_applied_any = True
                    for s in ast_res.metadata.get("ast_summaries", []):
                        all_ast_summaries.append(AstSummary(**s))

            # Stage 2: Semantic Compaction on remaining prose
            if self.settings.semantic_compaction_enabled and count_tokens(content) > 128:
                sem_res = self.semantic_compactor.compact(content, ctx)
                content = sem_res.compacted_text
                total_kept_sentences += sem_res.metadata.get("semantic_sentences_kept", 0)
                total_dropped_sentences += sem_res.metadata.get("semantic_sentences_dropped", 0)

            compacted_middle.append(
                ChatMessage(
                    role=msg.role,
                    content=content,
                    name=msg.name,
                    tool_calls=msg.tool_calls,
                    tool_call_id=msg.tool_call_id,
                )
            )

        # Recombine prefix + compacted middle + preserved recent tail
        reconstructed_messages = prefix_msgs + compacted_middle + recent_msgs
        compacted_tokens = count_messages_tokens(reconstructed_messages)
        tokens_saved = max(0, original_tokens - compacted_tokens)
        compression_ratio = round(compacted_tokens / max(1, original_tokens), 4)

        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

        # TTFT model: average local LLM prefill speed ~350 tokens/sec (2.85 ms per token)
        # Prefill time saved = tokens_saved * 2.85 ms
        estimated_ttft_saved_ms = round(tokens_saved * 2.85, 1)

        metadata = CompactionMetadata(
            original_tokens=original_tokens,
            compacted_tokens=compacted_tokens,
            tokens_saved=tokens_saved,
            compression_ratio=compression_ratio,
            duration_ms=duration_ms,
            estimated_ttft_saved_ms=estimated_ttft_saved_ms,
            strategy_used=active_strategy,
            ast_applied=ast_applied_any,
            ast_summaries=all_ast_summaries,
            semantic_sentences_kept=total_kept_sentences,
            semantic_sentences_dropped=total_dropped_sentences,
            kv_prefix_hash=prefix_hash,
        )

        return reconstructed_messages, metadata

    def compact_text(
        self,
        text: str,
        target_ratio: Optional[float] = None,
        strategy: Optional[str] = None,
        query_context: Optional[str] = None,
    ) -> Tuple[str, CompactionMetadata]:
        """Compact a standalone prompt or code document directly."""
        start_time = time.perf_counter()
        original_tokens = count_tokens(text)

        active_ratio = target_ratio or self.settings.target_ratio
        active_strategy = strategy or self.settings.default_strategy

        ctx = CompactorContext(
            target_ratio=active_ratio,
            strategy=active_strategy,
            query_context=query_context,
        )

        working_text = text
        ast_applied = False
        ast_summaries: List[AstSummary] = []

        # Stage 1: AST compaction
        if self.settings.ast_compaction_enabled:
            ast_res = self.ast_compactor.compact(working_text, ctx)
            working_text = ast_res.compacted_text
            if ast_res.metadata.get("ast_applied"):
                ast_applied = True
                for s in ast_res.metadata.get("ast_summaries", []):
                    ast_summaries.append(AstSummary(**s))

        # Stage 2: Semantic compaction
        kept_sentences = 0
        dropped_sentences = 0
        if self.settings.semantic_compaction_enabled and count_tokens(working_text) > 80:
            sem_res = self.semantic_compactor.compact(working_text, ctx)
            working_text = sem_res.compacted_text
            kept_sentences = sem_res.metadata.get("semantic_sentences_kept", 0)
            dropped_sentences = sem_res.metadata.get("semantic_sentences_dropped", 0)

        compacted_tokens = count_tokens(working_text)
        tokens_saved = max(0, original_tokens - compacted_tokens)
        compression_ratio = round(compacted_tokens / max(1, original_tokens), 4)
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        estimated_ttft_saved_ms = round(tokens_saved * 2.85, 1)

        metadata = CompactionMetadata(
            original_tokens=original_tokens,
            compacted_tokens=compacted_tokens,
            tokens_saved=tokens_saved,
            compression_ratio=compression_ratio,
            duration_ms=duration_ms,
            estimated_ttft_saved_ms=estimated_ttft_saved_ms,
            strategy_used=active_strategy,
            ast_applied=ast_applied,
            ast_summaries=ast_summaries,
            semantic_sentences_kept=kept_sentences,
            semantic_sentences_dropped=dropped_sentences,
            kv_prefix_hash=None,
        )

        return working_text, metadata
