# ContextForge integration guide

ContextForge acts as an OpenAI-compatible proxy. It can be integrated into local LLM runtimes, agent frameworks, and developer IDEs.

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

## 2. Developer tools and IDEs

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
3. Set **Model Name** to match your local model tag (e.g., `qwen2.5-coder:32b`).
4. Set **API Key** to any value.

ContextForge automatically intercepts incoming project context, compresses docstrings and auxiliary files, and streams the generation back into your editor.

---

## 3. Python SDKs and frameworks

### OpenAI Python SDK

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="contextforge",
)

response = client.chat.completions.create(
    model="llama3:70b",
    messages=[
        {"role": "system", "content": "You are a code refactoring expert."},
        {"role": "user", "content": "Here is the codebase...\n...40k tokens..."},
        {"role": "user", "content": "Refactor the database connection pool."},
    ],
    stream=True,
)

for chunk in response:
    print(chunk.choices[0].delta.content or "", end="", flush=True)
```

### LangChain

```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    base_url="http://localhost:8000/v1",
    api_key="contextforge",
    model="llama3:70b",
    temperature=0.2,
)

result = llm.invoke("Summarize this 30,000 token architectural document...")
print(result.content)
```

### LlamaIndex

```python
from llama_index.llms.openai_like import OpenAILike

llm = OpenAILike(
    api_base="http://localhost:8000/v1",
    api_key="contextforge",
    model="llama3:70b",
    is_chat_model=True,
)

response = llm.complete("Explain the cache synchronization protocol.")
print(response.text)
```
