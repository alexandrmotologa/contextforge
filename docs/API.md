# ContextForge API reference

ContextForge exposes an OpenAI-compatible reverse proxy API alongside direct management and telemetry endpoints.

---

## 1. Chat completions proxy

### `POST /v1/chat/completions`

Intercepts chat completion requests, applies context compaction to messages, and forwards the streamlined payload to the upstream LLM runner.

#### Request body

Follows the standard OpenAI chat completions specification with optional ContextForge control parameters and native tool calling support:

```json
{
  "model": "llama3:70b",
  "messages": [
    {
      "role": "system",
      "content": "You are an experienced systems architect."
    },
    {
      "role": "user",
      "content": "Here is the data pipeline source code:\n\n```python\nclass IngestionEngine:\n    def process(self): ...\n```"
    },
    {
      "role": "user",
      "content": "How does error retry logic operate in this engine?"
    }
  ],
  "stream": true,
  "temperature": 0.2,
  "compress": true,
  "target_ratio": 0.45,
  "strategy": "auto",
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "lookup_schema",
        "description": "Fetch database table definition",
        "parameters": {
          "type": "object",
          "properties": {
            "table_name": {"type": "string"}
          },
          "required": ["table_name"]
        }
      }
    }
  ],
  "tool_choice": "auto"
}
```

#### Custom request fields

- `compress` *(boolean, optional, default: true)*: Set to `false` to pass the request directly to the upstream model without compaction.
- `target_ratio` *(float, optional, default: 0.45)*: Desired token retention ratio (0.10 to 0.90).
- `strategy` *(string, optional, default: "auto")*: Compaction preset: `auto`, `balanced`, `aggressive`, `code_focused`, or `conservative`. When set to `auto`, ContextForge analyzes code and log density to dynamically select the best compression pipeline.
- `tools` *(array, optional)*: OpenAI tool definitions. ContextForge automatically shields tool definitions from compaction.
- `tool_choice` *(string or object, optional)*: Specifies which tool to invoke.
- `response_format` *(object, optional)*: Guides structured JSON output schemas.

#### Response headers (streaming)

When streaming with `stream: true`, the following HTTP headers accompany the SSE stream:

- `X-ContextForge-Saved-Tokens`: Total number of prompt tokens eliminated before reaching the upstream engine.
- `X-ContextForge-Compression-Ratio`: The ratio of compacted tokens to original tokens (for example, `0.380`).

#### Buffered response payload

When `stream: false`, the response matches the standard OpenAI completion format with an augmented `usage` object and a `contextforge_compaction` metadata block:

```json
{
  "id": "chatcmpl-cf-8f2a1b9c",
  "object": "chat.completion",
  "model": "llama3:70b",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "The error retry logic operates with an exponential backoff..."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 18316,
    "completion_tokens": 340,
    "total_tokens": 18656,
    "prompt_tokens_saved": 29884,
    "original_prompt_tokens": 48200,
    "compression_ratio": 0.380
  },
  "contextforge_compaction": {
    "original_tokens": 48200,
    "compacted_tokens": 18316,
    "tokens_saved": 29884,
    "compression_ratio": 0.380,
    "duration_ms": 8.42,
    "estimated_ttft_saved_ms": 1108.5,
    "strategy_used": "auto (code_focused)",
    "ast_applied": true,
    "kv_prefix_hash": "a8f419c0b2e7"
  }
}
```

---

## 2. Models endpoint

### `GET /v1/models`

Forwards model discovery calls to the active upstream engine. If the primary runner is unreachable and a fallback pool is configured, it checks backup engines before returning a default passthrough definition.

---

## 3. Direct compression endpoint

### `POST /api/compress`

Compacts raw text, markdown, or code without forwarding to an LLM. Useful for standalone processing pipelines, pre-processing, and testing.

#### Request body

```json
{
  "content": "def run_analysis():\n    \"\"\"Extended documentation.\"\"\"\n    return 42",
  "strategy": "auto",
  "target_ratio": 0.40,
  "query_context": "What does run_analysis return?"
}
```

#### Response

```json
{
  "compacted_content": "def run_analysis():\n    return 42",
  "metadata": {
    "original_tokens": 28,
    "compacted_tokens": 12,
    "tokens_saved": 16,
    "compression_ratio": 0.428,
    "duration_ms": 1.84,
    "estimated_ttft_saved_ms": 32.0,
    "strategy_used": "auto (code_focused)",
    "ast_applied": true
  }
}
```

---

## 4. Speculative KV-cache pre-warming

### `POST /api/warm`

Pre-warms upstream KV caches for long system prompts or codebase schemas ahead of time. ContextForge canonicalizes the prefix and executes a 1-token prefill on the target upstream runner.

#### Request body

```json
{
  "prefix": "You are a code review assistant with full awareness of the ContextForge engine...",
  "model": "llama3:70b"
}
```

#### Response

```json
{
  "status": "warmed",
  "prefix_hash": "a8f419c0b2e7",
  "estimated_tokens": 1280
}
```

---

## 5. Telemetry and statistics

### `GET /api/stats`

Returns cumulative token savings, average compression ratios, and pool health.

```json
{
  "status": "healthy",
  "upstream_url": "http://localhost:11434",
  "default_strategy": "auto",
  "target_ratio": 0.45,
  "telemetry": {
    "total_requests": 1842,
    "total_original_tokens": 7524800,
    "total_compacted_tokens": 2904575,
    "total_tokens_saved": 4620225,
    "overall_reduction_pct": 61.4,
    "avg_compression_ratio": 0.386,
    "total_ttft_saved_seconds": 184.81
  }
}
```

### `GET /api/history?limit=50`

Returns a list of recent compaction transactions, including request IDs, models, endpoints, duration, and token reduction metrics.

### `GET /api/export?format=json` or `?format=csv`

Exports the compaction telemetry database as downloadable JSON or CSV files for analytics, auditing, and benchmark reporting.

---

## 6. Prometheus metrics

### `GET /metrics`

Exposes real-time Prometheus metrics in standard text exposition format:

- `contextforge_requests_total`: Total number of requests intercepted by status code.
- `contextforge_tokens_original_total`: Cumulative uncompressed tokens received.
- `contextforge_tokens_saved_total`: Cumulative tokens eliminated before prefill.
- `contextforge_ttft_saved_seconds_total`: Estimated cumulative GPU prefill seconds saved.
- `contextforge_upstream_failovers_total`: Count of upstream failover events triggered.

---

## 7. Real-time WebSocket telemetry

### `WebSocket /ws/telemetry`

Streams live telemetry updates whenever requests complete:

```json
{
  "type": "compaction_event",
  "data": {
    "timestamp": 1773356000.12,
    "model": "llama3:70b",
    "original_tokens": 48200,
    "compacted_tokens": 18316,
    "tokens_saved": 29884,
    "ratio": 0.380,
    "duration_ms": 8.42
  }
}
```

---

## 8. Health check

### `GET /health`

Validates that ContextForge is operational and tests reachability across configured upstream runners in the failover pool.

```json
{
  "status": "online",
  "service": "ContextForge",
  "version": "0.1.0",
  "upstream_url": "http://localhost:11434",
  "upstream_reachable": true
}
```
