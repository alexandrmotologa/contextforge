"""Base interfaces and data structures for ContextForge compaction engines."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Set
from pydantic import BaseModel, Field


class CompactorContext(BaseModel):
    """Context and constraints for a compaction run."""

    target_ratio: float = Field(default=0.45, ge=0.05, le=1.0)
    strategy: str = Field(default="balanced")  # balanced, aggressive, code_focused, conservative
    query_context: Optional[str] = Field(
        default=None,
        description="The active user prompt or question used to guide salience and symbol retention",
    )
    pinned_symbols: Set[str] = Field(
        default_factory=set,
        description="Explicit function, class, or variable names that must never be skeletonized",
    )
    max_tokens: Optional[int] = Field(
        default=None,
        description="Hard token budget cap",
    )


class CompactionResult(BaseModel):
    """Result of a compaction operation."""

    compacted_text: str
    original_tokens: int
    compacted_tokens: int
    tokens_saved: int
    compression_ratio: float
    metadata: Dict[str, Any] = Field(default_factory=dict)


class BaseCompactor(ABC):
    """Abstract base class for all compaction implementations."""

    @abstractmethod
    def compact(self, text: str, context: CompactorContext) -> CompactionResult:
        """Compact text according to context constraints and return results."""
        pass
