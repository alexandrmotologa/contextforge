# ContextForge architecture and internal mechanics

ContextForge operates as an intelligent streaming reverse proxy between generative AI client tooling and local inference runtimes. This document details the technical design of its components: KV-cache prefix partitioning, AST code skeletonization, polyglot compaction, tool call safeguarding, adaptive auto-tuning, graph-based extractive semantic compaction, upstream failover, and Prometheus telemetry.

---

## 1. The long-context efficiency bottleneck

When sending long prompts (32k to 128k tokens) to local models running on Ollama, vLLM, or llama.cpp, latency and memory usage grow rapidly:

- **Attention prefill complexity:** Processing 64k tokens in a single forward pass takes multiple seconds of GPU compute, delaying the first generated token.
- **KV-cache VRAM footprint:** For a 70B parameter model with Grouped-Query Attention (GQA), each 1,000 prompt tokens occupy roughly 120MB of VRAM in FP16. At 64k tokens, the KV cache demands 7.6GB of GPU memory per concurrent stream.
- **Cache invalidation from non-deterministic prefixes:** Small differences in prompt formatting, whitespace, or timestamp tokens prevent local inference engines from reusing KV caches across turns.

ContextForge reduces total prompt token volume before prefill begins and canonicalizes static prefixes to maximize cache hits.

---

## 2. Compaction pipeline overview

The pipeline operates in sequential stages:

```
Raw Request Messages & Tool Definitions
       |
       v
[Stage 0: ToolGuard & Schema Isolation]
   +-- Detects JSON schemas, function tools, and strict call contracts
   +-- Replaces tools with unique token guards: __CF_TOOL_GUARD_<id>__
       |
       v
[Stage 1: Adaptive Strategy Classifier & Dynamic Budgeting]
   +-- Analyzes code density, log signatures, and prompt length
   +-- Auto-selects preset: code_focused, aggressive, conservative, balanced
   +-- Enforces recent_token_budget to prevent chat turn bloat
       |
       v
[Stage 2: KV-Cache Splitter]
   +-- Static system prefix (Canonicalized whitespace -> SHA-256 fingerprint)
   +-- Compressible middle history (Passed to compaction)
   +-- Recent turns (Preserved verbatim within dynamic budget)
       |
       v
[Stage 3: Polyglot AST Code Compactor]
   +-- Python: Standard AST parsing, import deduplication, helper pruning
   +-- TypeScript/JavaScript: ES6 import merging, JSDoc trimming, private stripping
   +-- Go: Interface preservation, unexported function body stubbing
   +-- Rust: Struct/impl preservation, private fn stubbing with todo!()
       |
       v
[Stage 4: Extractive Semantic Compactor]
   +-- BM25 query salience matching
   +-- TextRank sentence graph ranking
   +-- Duplicate line and repetitive log suppression
       |
       v
[Stage 5: Tool Restoration & Reconstruction]
   +-- Restores shielded tool definitions and schema blocks verbatim
   +-- Reassembles prompt with canonical system prefix
       |
       v
[Stage 6: Gateway & Failover Pool]
   +-- Proxies request to active upstream runner (Ollama / vLLM / llama.cpp)
   +-- Automatic fallback switch upon connection failure or timeout
   +-- Emits Prometheus counters and live WebSocket events
```

---

## 3. ToolGuard and schema protection

Language models fail when schema contracts are altered by semantic summarization. ToolGuard prevents this failure:

1. **Detection:** Scans incoming payloads for structured tool definitions, JSON schemas, function signatures, and explicit tool responses.
2. **Token Shielding:** Extracts schema blocks and replaces them with inert placeholders: `__CF_TOOL_GUARD_<id>__`.
3. **Pipeline Immunity:** Compaction passes (AST pruning and TextRank) treat placeholders as single lexical units without altering internal keys or types.
4. **Verbatim Restoration:** Replaces placeholders with the original JSON structure before sending to the model runner.

---

## 4. Adaptive strategy classification and dynamic budgeting

When requests specify `strategy: "auto"`, ContextForge analyzes the prompt payload:

- **Code density check:** If fenced code blocks or programming syntax exceed 30% of total tokens, the engine selects `code_focused`.
- **Log pattern check:** If repeated log lines or trace outputs exceed 25% of content, it selects `aggressive`.
- **Length threshold:** Prompts exceeding 60,000 tokens default to `aggressive` to preserve VRAM; prompts below 8,000 tokens default to `conservative` to protect context.
- **Dynamic token budget:** Ensures that recent dialogue history is retained up to a dedicated token limit (default 4,096 tokens) regardless of turn count.

---

## 5. Polyglot AST and structural code compaction

In programming prompts, 40% to 70% of tokens consist of helper functions, verbose comments, or repeated imports not referenced in the active query.

### Python AST analyzer
- **Import deduplication:** Merges repeated `from module import a` statements, sorts import lists, and eliminates unused duplicates.
- **Symbol pinning:** Extracts symbol names from the user query. Any function or class matching query keywords is pinned and kept intact.
- **Skeletonization:** Helper functions not referenced in the query have their bodies replaced with `...`. Special methods like `__init__` are preserved.
- **Docstring trimming:** Prunes long docstrings to single-line summaries or eliminates them in aggressive mode.

### TypeScript and JavaScript
- Merges ES6 `import { a, b } from "module"` statements.
- Strips JSDoc comments while preserving TypeScript interfaces and type aliases.
- Replaces non-pinned private class methods with minimal stubs.

### Go
- Preserves exported functions (`func Exported()`) and struct interfaces.
- Stubs unexported helper functions (`func privateHelper() { /* ... */ }`) if not pinned by the query.

### Rust
- Preserves `pub fn` functions, `struct`, `enum`, and trait contracts.
- Stubs internal non-pub functions with `todo!()` bodies when not pinned.

---

## 6. Semantic extraction engine

Natural language sections in the prompt (documentation, instructions, previous turns) are compacted using dual ranking:

### BM25 query salience
Calculates term frequency and inverse document frequency of query keywords across each candidate sentence in the prompt. Sentences containing query terms receive elevated retention weights.

### TextRank sentence graph
Builds a graph where nodes represent sentences and edge weights represent token overlap (Jaccard similarity). Power iteration calculates eigenvector centrality, identifying core informational nodes while pruning rhetorical filler.

### Log and repeat suppression
Detects consecutive lines sharing identical prefixes (such as server logs or loop outputs) and condenses them into a single summary notation: `[repeated 4 times: ...]`.

---

## 7. Upstream failover pool and telemetry

ContextForge handles backend infrastructure reliability:

- **Upstream Failover Pool:** Accepts an ordered list of candidate URLs (`CONTEXTFORGE_UPSTREAM_URL` plus `CONTEXTFORGE_UPSTREAM_FALLBACKS`). If the primary inference engine fails with a connection error or timeout, ContextForge retries against backup nodes transparently.
- **Prometheus Telemetry:** Exposes real-time counters for requests, original tokens, saved tokens, TTFT reduction seconds, and failover switch events at `GET /metrics`.
- **Live WebSocket Feed:** Broadcasts transaction telemetry over `ws://host:port/ws/telemetry` for live monitoring on the web dashboard.
