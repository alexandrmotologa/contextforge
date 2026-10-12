# ContextForge integration guide

ContextForge acts as an OpenAI-compatible proxy. It can be integrated into local LLM runtimes, agent frameworks, developer IDEs, and observability stacks.

---

## 1. Local LLM runtimes

### Ollama

Start Ollama normally:

```bash
ollama serve
```

Run ContextForge pointing to Ollama's port (11434):

```bash
contextforge serve --host 0.0.0.0 --port 8000 --upstream http://localhost:11434
```

Now direct your client applications to `http://localhost:8000/v1` instead of `http://localhost:11434/v1`.

### vLLM

Run your vLLM server with PagedAttention and prefix caching enabled:

```bash
vllm serve meta-llama/Meta-Llama-3-70B-Instruct \
  --port 8080 \
  --enable-prefix-caching \
  --max-model-len 65536
```

Start ContextForge:

```bash
contextforge serve --port 8000 --upstream http://localhost:8080
```

### LM Studio

1. In LM Studio, start the Local Inference Server on port 1234.
2. Enable CORS and ensure your desired model is loaded.
3. Start ContextForge:

```bash
contextforge serve --port 8000 --upstream http://localhost:1234
```

### llama.cpp (llama-server)

Start `llama-server` with prompt caching:

```bash
./llama-server -m models/Meta-Llama-3-70B-Instruct-Q4_K_M.gguf -c 65536 --port 8080 --prompt-cache
```

Start ContextForge:

```bash
contextforge serve --port 8000 --upstream http://localhost:8080
```

---

## 2. Upstream Failover Pool configuration

To provide resilience against GPU server restarts, crash recoveries, or multi-node local inference clusters, configure a failover pool:

```bash
# Comma-separated list of secondary backends
export CONTEXTFORGE_UPSTREAM_URL="http://gpu-primary:8000"
export CONTEXTFORGE_UPSTREAM_FALLBACKS="http://gpu-secondary:8000,http://cpu-backup:11434"

contextforge serve --port 8000
```

If the primary node experiences connection timeouts or network drops, ContextForge redirects the request to the next reachable candidate and tracks the event in Prometheus.

---

## 3. Developer tools and IDEs

### Open WebUI

In the Open WebUI administrative settings:
1. Navigate to **Settings > Connections > OpenAI API**.
2. Set **URL** to: `http://localhost:8000/v1` (or your host IP if running in Docker).
3. Set **API Key** to: `contextforge` (or any non-empty string).
4. Save and verify that your upstream models appear in the model selection dropdown.

### Cursor / Cline / Roo-Code

In your editor or agent settings:
1. Select **OpenAI Compatible** provider.
2. Set **Base URL** to `http://localhost:8000/v1`.
3. Set **Model Name** to match your local model tag (for example, `qwen2.5-coder:32b`).
4. Set **API Key** to any value.

ContextForge automatically intercepts incoming project context, compresses docstrings and auxiliary files, protects tools and schemas, and streams generation back into your editor.

---

## 4. Agent frameworks and tool calling

ContextForge natively safeguards function definitions, JSON schemas, and structured outputs from compression degradation via ToolGuard:

### OpenAI Python SDK with tools

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="contextforge",
)

tools = [
    {
        "type": "function",
        "function": {
            "name": "read_source_file",
            "description": "Read file contents from filesystem",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"}
                },
                "required": ["path"]
            }
        }
    }
]

response = client.chat.completions.create(
    model="qwen2.5-coder:32b",
    messages=[
        {"role": "system", "content": "You are a software engineer."},
        {"role": "user", "content": "Analyze repo structure and inspect main.py"},
    ],
    tools=tools,
    tool_choice="auto",
    extra_body={"strategy": "auto"}
)

print(response.choices[0].message)
```

### LangChain

```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    base_url="http://localhost:8000/v1",
    api_key="contextforge",
    model="llama3:70b",
    temperature=0.2,
    model_kwargs={"extra_body": {"strategy": "code_focused"}}
)

result = llm.invoke("Summarize this 30,000 token architectural document...")
print(result.content)
```

---

## 5. Prometheus and Grafana observability

ContextForge exposes standard Prometheus metrics at `GET /metrics`.

### Prometheus configuration (`prometheus.yml`)

Add ContextForge to your scrape targets:

```yaml
scrape_configs:
  - job_name: 'contextforge'
    scrape_interval: 10s
    static_configs:
      - targets: ['localhost:8000']
```

### Key metrics to graph

- `contextforge_tokens_saved_total`: Track cumulative prompt token reduction.
- `contextforge_ttft_saved_seconds_total`: Graph GPU compute seconds saved across workers.
- `contextforge_upstream_failovers_total`: Alert on upstream backend dropouts and failover triggers.
- `contextforge_requests_total`: Monitor traffic volume and proxy throughput.
