# ContextForge architecture and internal mechanics

ContextForge operates as an intelligent streaming reverse proxy between generative AI client tooling and local inference runtimes. This document details the technical design of its four core stages: KV-cache prefix partitioning, AST code skeletonization, graph-based extractive semantic compaction, and the async streaming reverse proxy.

---

## 1. The long-context efficiency bottleneck

When sending long prompts (32k to 128k tokens) to local models running on Ollama, vLLM, or llama.cpp, latency and memory usage grow rapidly:

- **Attention prefill complexity:** Even with FlashAttention-2 or FlashInfer, processing 64k tokens in a single forward pass takes multiple seconds of GPU compute.
- **KV-cache VRAM footprint:** For a 70B parameter model with Grouped-Query Attention (GQA), each 1,000 prompt tokens occupy roughly 120MB of VRAM in FP16. At 64k tokens, the KV cache alone demands 7.6GB of GPU memory per concurrent stream.
- **Cache invalidation from non-deterministic prefixes:** Small differences in prompt formatting, whitespace, or timestamp tokens prevent local inference engines from reusing KV caches across turns.

ContextForge reduces total prompt token volume before prefill begins and canonicalizes static prefixes to maximize cache hits.

---

## 2. Compaction pipeline overview

The pipeline operates in four sequential stages:

```
Raw Request Messages
       |
       v
[Stage 1: KV-Cache Splitter]
  +-- Static system prefix (Canonicalized whitespace -> Hash)
  +-- Compressible middle history (Passed to compaction)
  +-- Recent turns (Preserved 100% without modification)
       |
       v
[Stage 2: AST Code Compactor]
  +-- Regex extraction of markdown fences & raw code
  +-- Python AST parsing & import deduplication
  +-- Helper skeletonization & docstring trimming
  +-- Polyglot fallback for other languages
       |
       v
[Stage 3: Semantic Compactor]
  +-- BM25 query salience matching
  +-- TextRank sentence graph ranking
  +-- Duplicate line suppression
       |
       v
[Stage 4: Reconstruction & Gateway]
  +-- Reassembled prompt with preserved system prefix
  +-- Forwarded to local LLM via httpx streaming
```

---

## 3. Stage 1: KV-cache prefix optimization

Local LLM backends such as vLLM (via PagedAttention) and llama.cpp support prefix caching. If two requests share an identical prompt prefix, the runtime skips computing attention keys and values for those tokens, loading them directly from GPU memory.

ContextForge enforces prefix determinism:

1. **Whitespace canonicalization:** Normalizes carriage returns (`\r\n` to `\n`), trims trailing spaces from lines, and collapses multi-line blank runs into single clean separators.
2. **Turn partitioning:** Divides the conversation list into three sections:
   - **Prefix:** Leading system messages. These are canonicalized and fingerprinted with SHA-256.
   - **Middle history:** Earlier multi-turn dialogue, code samples, and previous system responses. This section undergoes AST and semantic compaction.
   - **Tail:** The most recent user questions and assistant answers (configurable via `preserve_recent_turns`, default 3). This tail is never compressed, ensuring that recent references and exact instructions remain untouched.

---

## 4. Stage 2: AST code compaction

In programming prompts, 40% to 70% of tokens often consist of non-critical code details, including verbose docstrings, repetitive comments, and auxiliary helper functions that the active user query does not reference.

ContextForge implements authentic AST analysis using Python's standard `ast` module:

### Import deduplication
Scans module imports, merges repeated `from module import a` statements, sorts import lists, and eliminates duplicate packages.

### Symbol pinning
Extracts symbol names mentioned in the user's active query. Any function, class, or method whose name overlaps with the query is marked as pinned.

### Skeletonization
For functions that are not pinned:
- Helper functions with multi-line bodies are replaced with an ellipsis body: `...`
- Class signatures and public methods are preserved so the model understands the interface structure.
- Special methods like `__init__` and `__call__` are preserved to retain initialization contracts.

### Docstring compaction
- **In balanced mode:** Multiline docstrings are trimmed to their first summary sentence.
- **In aggressive mode:** Docstrings of non-pinned functions are pruned entirely.

### Polyglot fallback
For non-Python blocks (JavaScript, TypeScript, Go, Rust, JSON, SQL), ContextForge detects language fences and applies comment stripping, blank line consolidation, and log pattern deduplication.

---

## 5. Stage 3: Semantic extraction engine

Natural language sections in the prompt (documentation, instructions, previous chat turns) are compacted using a combination of two algorithms:

### BM25 query salience
Calculates term frequency and inverse document frequency of query keywords across each candidate sentence in the prompt. Sentences containing query terms receive elevated retention weights.

### TextRank sentence graph
Builds a graph where nodes represent sentences and edge weights represent token overlap (Jaccard similarity). Power iteration calculates eigenvector centrality, identifying core informational nodes while pruning rhetorical filler.

### Log and repeat suppression
Detects consecutive lines sharing identical prefixes (such as repeating server logs or loop outputs) and condenses them into a single summary notation: `[repeated 4 times: ...]`

---

## 6. Stage 4: Streaming SSE reverse proxy

ContextForge implements an asynchronous reverse proxy powered by FastAPI and httpx:

- **Full streaming support:** Handles `text/event-stream` chunks from upstream runners, passing tokens to clients with minimal proxy overhead (less than 1ms per chunk).
- **Time to first token (TTFT) instrumentation:** Tracks the exact timestamp when the upstream runtime returns its first response token, computing TTFT savings against estimated uncompressed baselines.
- **Telemetry logging:** Asynchronously records request metrics (model, token delta, duration, KV prefix hash, and compression ratio) into a local SQLite database (`data/contextforge.db`).
