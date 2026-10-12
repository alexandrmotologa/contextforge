"""Pydantic schemas for OpenAI API compatibility, compaction telemetry, and requests."""

from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """A single message in an OpenAI chat completion conversation."""

    role: Literal["system", "user", "assistant", "tool", "function"]
    content: Optional[str] = None
    name: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None


class ChatCompletionRequest(BaseModel):
    """OpenAI-compatible chat completion request schema."""

    model: str
    messages: List[ChatMessage]
    temperature: Optional[float] = 1.0
    top_p: Optional[float] = 1.0
    n: Optional[int] = 1
    stream: Optional[bool] = False
    stop: Optional[Union[str, List[str]]] = None
    max_tokens: Optional[int] = None
    presence_penalty: Optional[float] = 0.0
    frequency_penalty: Optional[float] = 0.0
    user: Optional[str] = None

    # ContextForge extension parameters (optional)
    compress: Optional[bool] = Field(
        default=True,
        description="Whether to run context compaction on this request",
    )
    target_ratio: Optional[float] = Field(
        default=None,
        description="Override target compaction ratio (e.g. 0.45)",
    )
    strategy: Optional[Literal["balanced", "aggressive", "code_focused", "conservative"]] = Field(
        default=None,
        description="Compaction strategy preset override",
    )


class UsageInfo(BaseModel):
    """Token usage details for the completion."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    prompt_tokens_saved: Optional[int] = 0
    original_prompt_tokens: Optional[int] = None
    compression_ratio: Optional[float] = None


class ChatCompletionResponseChoice(BaseModel):
    """A completion choice in non-streaming response."""

    index: int
    message: ChatMessage
    finish_reason: Optional[str] = "stop"


class ChatCompletionResponse(BaseModel):
    """OpenAI-compatible chat completion response."""

    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[ChatCompletionResponseChoice]
    usage: Optional[UsageInfo] = None
    contextforge_compaction: Optional[Dict[str, Any]] = None


class DeltaMessage(BaseModel):
    """Delta payload in streaming chunk."""

    role: Optional[str] = None
    content: Optional[str] = None


class ChatCompletionChunkChoice(BaseModel):
    """Streaming chunk choice."""

    index: int
    delta: DeltaMessage
    finish_reason: Optional[str] = None


class ChatCompletionChunk(BaseModel):
    """OpenAI-compatible streaming chat completion chunk."""

    id: str
    object: str = "chat.completion.chunk"
    created: int
    model: str
    choices: List[ChatCompletionChunkChoice]


class AstSummary(BaseModel):
    """Metrics produced by the AST code compactor."""

    language: str
    original_lines: int
    compacted_lines: int
    functions_analyzed: int
    functions_skeletonized: int
    docstrings_trimmed: int
    imports_deduplicated: int
    reduction_percentage: float


class CompactionMetadata(BaseModel):
    """Detailed telemetry describing prompt compaction performance."""

    original_tokens: int
    compacted_tokens: int
    tokens_saved: int
    compression_ratio: float
    duration_ms: float
    estimated_ttft_saved_ms: float
    strategy_used: str
    ast_applied: bool
    ast_summaries: List[AstSummary] = Field(default_factory=list)
    semantic_sentences_kept: int = 0
    semantic_sentences_dropped: int = 0
    kv_prefix_hash: Optional[str] = None


class CompressRequest(BaseModel):
    """Direct API request to compress a prompt or text block."""

    content: str
    strategy: Literal["balanced", "aggressive", "code_focused", "conservative"] = "balanced"
    target_ratio: Optional[float] = 0.45
    query_context: Optional[str] = None
    language: Optional[str] = None


class CompressResponse(BaseModel):
    """Direct API response containing the compacted prompt and metrics."""

    compacted_content: str
    metadata: CompactionMetadata
