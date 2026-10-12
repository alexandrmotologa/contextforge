"""Configuration settings for ContextForge proxy and compaction engine."""

from pathlib import Path
from typing import Literal
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """ContextForge application configuration settings."""

    # Server settings
    host: str = Field(default="0.0.0.0", description="Host interface to bind the proxy server")
    port: int = Field(default=8000, description="Port to listen for OpenAI API requests")
    upstream_url: str = Field(
        default="http://localhost:11434",
        description="Upstream LLM server endpoint (e.g., Ollama, vLLM, LM Studio, llama.cpp)",
    )
    upstream_timeout: float = Field(
        default=120.0,
        description="Read timeout in seconds for upstream completions",
    )

    # Upstream failover pool
    upstream_fallbacks: list[str] = Field(
        default_factory=list,
        description="Fallback upstream LLM endpoints in order of priority",
    )

    # Compaction settings
    target_ratio: float = Field(
        default=0.45,
        ge=0.1,
        le=0.9,
        description="Target token count ratio after compression (0.45 means keep 45% of tokens)",
    )
    min_tokens_to_compress: int = Field(
        default=1024,
        ge=16,
        description="Minimum prompt token length before compaction triggers",
    )
    ast_compaction_enabled: bool = Field(
        default=True,
        description="Enable AST-aware code compaction for embedded source files and code blocks",
    )
    polyglot_compaction_enabled: bool = Field(
        default=True,
        description="Enable AST and structural compaction for TypeScript, JavaScript, Go, and Rust",
    )
    semantic_compaction_enabled: bool = Field(
        default=True,
        description="Enable graph-based extractive semantic compaction for natural language",
    )
    kv_cache_alignment_enabled: bool = Field(
        default=True,
        description="Enable canonical prompt prefix ordering for KV-cache reuse in local runtimes",
    )
    tool_protection_enabled: bool = Field(
        default=True,
        description="Protect tool calling definitions and JSON schemas from lossy compaction",
    )

    # Strategy configuration
    default_strategy: Literal["auto", "balanced", "aggressive", "code_focused", "conservative"] = Field(
        default="auto",
        description="Default compression preset: auto (adaptive classifier), balanced, aggressive, code_focused, conservative",
    )

    # Attention and recall safeguards
    preserve_recent_turns: int = Field(
        default=3,
        ge=1,
        description="Number of most recent conversation turns to keep untouched",
    )
    recent_token_budget: int = Field(
        default=4096,
        ge=256,
        description="Maximum uncompressed token budget reserved for recent conversation turns",
    )
    preserve_system_prompt: bool = Field(
        default=True,
        description="Preserve system instructions without lossy compression",
    )
    attention_sink_tokens: int = Field(
        default=4,
        ge=1,
        description="Number of initial prefix tokens to preserve for attention sink stability",
    )

    # Observability & Metrics
    prometheus_enabled: bool = Field(
        default=True,
        description="Expose Prometheus metrics endpoint at /metrics",
    )

    # Storage settings
    db_path: Path = Field(
        default=Path("data/contextforge.db"),
        description="Path to local SQLite database for telemetry and savings tracking",
    )

    model_config = SettingsConfigDict(
        env_prefix="CONTEXTFORGE_",
        env_file=".env",
        extra="ignore",
    )


def get_settings() -> Settings:
    """Return default or environment-configured settings instance."""
    return Settings()
