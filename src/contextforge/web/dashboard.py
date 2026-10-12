"""Embedded modern dark-mode dashboard for ContextForge proxy monitoring and interactive playground."""

import json
from typing import Any, Dict, List
from contextforge.core.config import Settings


def get_dashboard_html(stats: Dict[str, Any], recent: List[Dict[str, Any]], settings: Settings) -> str:
    """Generate the self-contained dashboard HTML."""
    total_reqs = stats.get("total_requests", 0)
    total_saved = stats.get("total_tokens_saved", 0)
    reduction_pct = stats.get("overall_reduction_pct", 0.0)
    avg_ratio = stats.get("avg_compression_ratio", 1.0)
    ttft_saved = stats.get("total_ttft_saved_seconds", 0.0)
    upstream = settings.upstream_url
    fallbacks_count = len(settings.upstream_fallbacks)

    recent_rows_html = ""
    if not recent:
        recent_rows_html = """<tr id="emptyRow"><td colspan="7" class="py-6 text-center text-slate-500">No requests proxied yet. Send requests to /v1/chat/completions or test below.</td></tr>"""
    else:
        for r in recent:
            reduction = round((1.0 - r["compression_ratio"]) * 100, 1)
            ast_badge = (
                '<span class="px-2 py-0.5 text-xs bg-cyan-950 text-cyan-400 border border-cyan-800 rounded">AST</span>'
                if r["ast_applied"]
                else '<span class="text-slate-600">-</span>'
            )
            stream_badge = (
                '<span class="text-emerald-400 font-medium">SSE</span>'
                if r["streaming"]
                else '<span class="text-slate-400">JSON</span>'
            )
            recent_rows_html += f"""
            <tr class="border-b border-slate-800/60 hover:bg-slate-800/30 text-sm transition-colors">
                <td class="py-3 px-4 font-mono text-xs text-slate-400">{r["id"][:12]}</td>
                <td class="py-3 px-4 font-medium text-slate-300">{r["model"]}</td>
                <td class="py-3 px-4">{stream_badge}</td>
                <td class="py-3 px-4 font-mono">{r["original_tokens"]:,} &rarr; <span class="text-cyan-400">{r["compacted_tokens"]:,}</span></td>
                <td class="py-3 px-4 font-semibold text-emerald-400">-{reduction}%</td>
                <td class="py-3 px-4">{ast_badge}</td>
                <td class="py-3 px-4 font-mono text-xs text-slate-400">{r["duration_ms"]} ms</td>
            </tr>
            """

    return f"""<!DOCTYPE html>
<html lang="en" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ContextForge | Intelligent LLM Context Compression Proxy</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        tailwind.config = {{
            darkMode: 'class',
            theme: {{
                extend: {{
                    colors: {{
                        brand: {{
                            dark: '#070a12',
                            card: '#0f172a',
                            border: '#1e293b',
                            cyan: '#00f5ff',
                            amber: '#f59e0b',
                        }}
                    }}
                }}
            }}
        }}
    </script>
    <style>
        body {{
            background-color: #070a12;
            color: #f1f5f9;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
        }}
        pre, code {{ font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }}
        @keyframes highlight {{
            0% {{ background-color: rgba(6, 182, 212, 0.25); }}
            100% {{ background-color: transparent; }}
        }}
        .new-row {{ animation: highlight 2.5s ease-out; }}
    </style>
</head>
<body class="min-h-screen flex flex-col">

    <!-- Header Navigation -->
    <header class="border-b border-slate-800/80 bg-slate-950/60 backdrop-blur px-6 py-4 flex items-center justify-between sticky top-0 z-50">
        <div class="flex items-center space-x-3">
            <div class="w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-400 to-blue-600 flex items-center justify-center font-bold text-slate-950 text-base shadow-lg shadow-cyan-500/20">CF</div>
            <div>
                <h1 class="font-bold text-lg tracking-tight flex items-center gap-2">
                    ContextForge
                    <span class="text-xs px-2 py-0.5 rounded-full bg-cyan-950 text-cyan-400 border border-cyan-800 font-normal">v0.1.0</span>
                </h1>
                <p class="text-xs text-slate-400">KV-Cache & Prompt Compaction Reverse Proxy</p>
            </div>
        </div>
        <div class="flex items-center space-x-4 text-xs">
            <div id="wsIndicator" class="flex items-center gap-2 px-3 py-1.5 rounded-md bg-slate-900 border border-slate-800">
                <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
                <span class="text-slate-400">Live WS:</span>
                <span id="wsStatusText" class="text-emerald-400 font-medium">Connected</span>
            </div>
            <div class="flex items-center gap-2 px-3 py-1.5 rounded-md bg-slate-900 border border-slate-800">
                <span class="text-slate-400">Upstream:</span>
                <span class="font-mono text-slate-200">{upstream}</span>
                {f'<span class="text-xs px-1.5 py-0.5 rounded bg-slate-800 text-slate-400">+{fallbacks_count} fallbacks</span>' if fallbacks_count > 0 else ''}
            </div>
            <a href="/metrics" target="_blank" class="px-3 py-1.5 rounded-md bg-slate-800 hover:bg-slate-700 text-slate-300 transition">Metrics</a>
            <a href="https://github.com/alexandrmotologa/contextforge" target="_blank" class="px-3 py-1.5 rounded-md bg-slate-800 hover:bg-slate-700 text-slate-300 transition">GitHub</a>
        </div>
    </header>

    <!-- Main Content Grid -->
    <main class="flex-1 max-w-7xl w-full mx-auto px-6 py-8 space-y-8">

        <!-- KPI Metrics Ribbon -->
        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <div class="p-5 rounded-xl bg-slate-900/80 border border-slate-800/80 shadow-sm relative overflow-hidden">
                <div class="text-xs font-semibold uppercase tracking-wider text-slate-400">Tokens Saved</div>
                <div id="kpiTokensSaved" class="text-3xl font-extrabold mt-2 text-cyan-400 font-mono">{total_saved:,}</div>
                <div id="kpiReduction" class="text-xs text-emerald-400 mt-1 flex items-center gap-1 font-medium">
                    &darr; {reduction_pct}% average reduction
                </div>
            </div>

            <div class="p-5 rounded-xl bg-slate-900/80 border border-slate-800/80 shadow-sm">
                <div class="text-xs font-semibold uppercase tracking-wider text-slate-400">Compression Ratio</div>
                <div id="kpiRatio" class="text-3xl font-extrabold mt-2 text-slate-100 font-mono">{avg_ratio:.2f}x</div>
                <div class="text-xs text-slate-400 mt-1">target: {settings.target_ratio * 100:.0f}%</div>
            </div>

            <div class="p-5 rounded-xl bg-slate-900/80 border border-slate-800/80 shadow-sm">
                <div class="text-xs font-semibold uppercase tracking-wider text-slate-400">TTFT Prefill Saved</div>
                <div id="kpiTtft" class="text-3xl font-extrabold mt-2 text-amber-400 font-mono">{ttft_saved:.1f}s</div>
                <div class="text-xs text-slate-400 mt-1">cumulative GPU latency eliminated</div>
            </div>

            <div class="p-5 rounded-xl bg-slate-900/80 border border-slate-800/80 shadow-sm">
                <div class="text-xs font-semibold uppercase tracking-wider text-slate-400">Total Requests</div>
                <div id="kpiRequests" class="text-3xl font-extrabold mt-2 text-slate-100 font-mono">{total_reqs:,}</div>
                <div class="text-xs text-slate-400 mt-1">proxy transactions logged</div>
            </div>
        </div>

        <!-- Interactive Compaction Playground -->
        <div class="rounded-xl bg-slate-900/60 border border-slate-800 p-6 space-y-6">
            <div class="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-800/80 pb-4">
                <div>
                    <h2 class="text-base font-semibold text-slate-100">Interactive Prompt Playground</h2>
                    <p class="text-xs text-slate-400">Test AST code skeletonization, semantic compaction, and visual diff in real-time.</p>
                </div>
                <div class="flex flex-wrap items-center gap-3">
                    <div>
                        <label class="text-xs text-slate-400 block mb-1">Strategy</label>
                        <select id="strategySelect" class="bg-slate-950 border border-slate-700 rounded px-2.5 py-1 text-xs text-slate-200 focus:outline-none focus:border-cyan-500">
                            <option value="auto" selected>Auto-Tune (Adaptive Classifier)</option>
                            <option value="balanced">Balanced (AST + Semantic)</option>
                            <option value="aggressive">Aggressive (Maximum Reduction)</option>
                            <option value="code_focused">Code Focused (Heavy AST Skeletons)</option>
                            <option value="conservative">Conservative (High Recall)</option>
                        </select>
                    </div>
                    <div>
                        <label class="text-xs text-slate-400 block mb-1">Target Ratio (<span id="ratioLabel">45%</span>)</label>
                        <input id="ratioSlider" type="range" min="15" max="85" value="45" class="accent-cyan-400 w-28 h-2 cursor-pointer">
                    </div>
                    <button id="compressBtn" class="mt-4 md:mt-0 px-4 py-2 rounded-lg bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-semibold text-xs tracking-wide transition shadow-lg shadow-cyan-500/20">
                        Compress Now
                    </button>
                </div>
            </div>

            <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <!-- Input Column -->
                <div class="space-y-3">
                    <div class="flex items-center justify-between text-xs text-slate-400">
                        <span class="font-medium">Raw Input Prompt / Code</span>
                        <span id="inputTokens" class="font-mono">Tokens: 0</span>
                    </div>
                    <textarea id="rawInput" rows="13" class="w-full bg-slate-950 border border-slate-800 rounded-lg p-3 text-xs font-mono text-slate-200 focus:outline-none focus:border-cyan-500 transition resize-y" placeholder="Paste your code or long prompt here...">def process_data(data: list) -> list:
    \"\"\"Process the input dataset line by line.\"\"\"
    cleaned = [d.strip() for d in data if d]
    return cleaned

def helper_one():
    \"\"\"Helper one implementation details with documentation.\"\"\"
    x = 10
    y = 20
    return x + y

def helper_two():
    \"\"\"Helper two implementation details.\"\"\"
    return [i * 2 for i in range(50)]

# Additional documentation and notes
The system runs background telemetry tasks every 30 seconds.
Memory usage is monitored across all worker processes.
Connection pools to PostgreSQL are maintained at max 20 connections.</textarea>
                    <div>
                        <input id="queryContext" type="text" class="w-full bg-slate-950 border border-slate-800 rounded px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-cyan-500" placeholder="Optional query context (e.g. How does process_data work?)">
                    </div>
                </div>

                <!-- Output Column with Diff Viewer -->
                <div class="space-y-3">
                    <div class="flex items-center justify-between text-xs text-slate-400">
                        <div class="flex items-center space-x-2">
                            <button id="tabOutput" class="px-2.5 py-1 rounded bg-slate-800 text-cyan-400 font-medium">Compacted Code</button>
                            <button id="tabDiff" class="px-2.5 py-1 rounded bg-transparent hover:bg-slate-800 text-slate-400 font-medium transition">Visual Diff</button>
                        </div>
                        <div class="space-x-2">
                            <span id="outputTokens" class="font-mono text-cyan-400">Tokens: -</span>
                            <span id="outputSavings" class="font-semibold text-emerald-400"></span>
                        </div>
                    </div>
                    <div id="outputContainer" class="relative">
                        <textarea id="compactedOutput" rows="13" readonly class="w-full bg-slate-950/80 border border-slate-800 rounded-lg p-3 text-xs font-mono text-slate-300 focus:outline-none resize-y" placeholder="Compacted output will appear here..."></textarea>
                        <div id="diffView" class="hidden w-full h-[250px] bg-slate-950/90 border border-slate-800 rounded-lg p-3 text-xs font-mono overflow-y-auto space-y-1"></div>
                    </div>
                    <div id="metadataPill" class="text-xs text-slate-400 py-1 font-mono">Ready to compress.</div>
                </div>
            </div>
        </div>

        <!-- Recent Transactions Log -->
        <div class="rounded-xl bg-slate-900/60 border border-slate-800 p-6 space-y-4">
            <div class="flex items-center justify-between">
                <div>
                    <h2 class="text-base font-semibold text-slate-100">Live Request Telemetry</h2>
                    <p class="text-xs text-slate-400">Captured in real-time via WebSocket /ws/telemetry</p>
                </div>
                <div class="flex items-center space-x-2">
                    <a href="/api/export?format=csv" class="px-3 py-1.5 rounded-md bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs transition">Export CSV</a>
                    <a href="/api/export?format=json" class="px-3 py-1.5 rounded-md bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs transition">Export JSON</a>
                </div>
            </div>
            <div class="overflow-x-auto">
                <table class="w-full text-left border-collapse">
                    <thead>
                        <tr class="border-b border-slate-800 text-xs font-semibold text-slate-400 uppercase tracking-wider">
                            <th class="py-3 px-4">Request ID</th>
                            <th class="py-3 px-4">Model</th>
                            <th class="py-3 px-4">Type</th>
                            <th class="py-3 px-4">Tokens (Before &rarr; After)</th>
                            <th class="py-3 px-4">Reduction</th>
                            <th class="py-3 px-4">AST</th>
                            <th class="py-3 px-4">Latency</th>
                        </tr>
                    </thead>
                    <tbody id="recentRowsTable" class="divide-y divide-slate-800/40">
                        {recent_rows_html}
                    </tbody>
                </table>
            </div>
        </div>
    </main>

    <footer class="border-t border-slate-800/80 py-4 text-center text-xs text-slate-500">
        ContextForge &bull; Open-Source Context Compression & KV-Cache Proxy &bull; MIT License
    </footer>

    <script>
        const rawInput = document.getElementById('rawInput');
        const queryContext = document.getElementById('queryContext');
        const ratioSlider = document.getElementById('ratioSlider');
        const ratioLabel = document.getElementById('ratioLabel');
        const strategySelect = document.getElementById('strategySelect');
        const compressBtn = document.getElementById('compressBtn');
        const compactedOutput = document.getElementById('compactedOutput');
        const diffView = document.getElementById('diffView');
        const outputTokens = document.getElementById('outputTokens');
        const outputSavings = document.getElementById('outputSavings');
        const metadataPill = document.getElementById('metadataPill');
        const inputTokens = document.getElementById('inputTokens');
        const tabOutput = document.getElementById('tabOutput');
        const tabDiff = document.getElementById('tabDiff');
        const recentRowsTable = document.getElementById('recentRowsTable');

        ratioSlider.addEventListener('input', (e) => {{
            ratioLabel.textContent = e.target.value + '%';
        }});

        function updateInputCount() {{
            const len = rawInput.value.length;
            const approx = Math.max(1, Math.round(len / 3.85));
            inputTokens.textContent = 'Approx Tokens: ' + approx;
        }}
        rawInput.addEventListener('input', updateInputCount);
        updateInputCount();

        // Tab Switching for Output vs Visual Diff
        tabOutput.addEventListener('click', () => {{
            tabOutput.className = 'px-2.5 py-1 rounded bg-slate-800 text-cyan-400 font-medium';
            tabDiff.className = 'px-2.5 py-1 rounded bg-transparent hover:bg-slate-800 text-slate-400 font-medium transition';
            compactedOutput.classList.remove('hidden');
            diffView.classList.add('hidden');
        }});

        tabDiff.addEventListener('click', () => {{
            tabDiff.className = 'px-2.5 py-1 rounded bg-slate-800 text-cyan-400 font-medium';
            tabOutput.className = 'px-2.5 py-1 rounded bg-transparent hover:bg-slate-800 text-slate-400 font-medium transition';
            compactedOutput.classList.add('hidden');
            diffView.classList.remove('hidden');
        }});

        function renderDiff(original, compacted) {{
            const origLines = original.split('\\n');
            const compSet = new Set(compacted.split('\\n').map(l => l.trim()));
            diffView.innerHTML = '';

            origLines.forEach(line => {{
                const trimmed = line.trim();
                const div = document.createElement('div');
                div.className = 'py-0.5 px-2 rounded';
                if (!trimmed) {{
                    div.innerHTML = '&nbsp;';
                }} else if (compSet.has(trimmed)) {{
                    div.className += ' text-slate-300 bg-slate-900/50';
                    div.textContent = '  ' + line;
                }} else {{
                    div.className += ' text-rose-400 line-through bg-rose-950/20 opacity-75';
                    div.textContent = '- ' + line;
                }}
                diffView.appendChild(div);
            }});
        }}

        compressBtn.addEventListener('click', async () => {{
            const content = rawInput.value;
            if (!content.trim()) return;

            compressBtn.disabled = true;
            compressBtn.textContent = 'Compressing...';
            metadataPill.textContent = 'Analyzing syntax & calculating salience...';

            try {{
                const res = await fetch('/api/compress', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{
                        content: content,
                        strategy: strategySelect.value,
                        target_ratio: parseInt(ratioSlider.value, 10) / 100.0,
                        query_context: queryContext.value || null
                    }})
                }});

                if (!res.ok) throw new Error('Compression failed: ' + res.statusText);

                const data = await res.json();
                compactedOutput.value = data.compacted_content;
                renderDiff(content, data.compacted_content);
                outputTokens.textContent = 'Tokens: ' + data.metadata.compacted_tokens;
                outputSavings.textContent = '-' + Math.round((1 - data.metadata.compression_ratio) * 100) + '% (' + data.metadata.tokens_saved + ' saved)';
                metadataPill.textContent = 'Strategy: ' + data.metadata.strategy_used + ' | ' + data.metadata.duration_ms + 'ms | Estimated TTFT speedup: ~' + data.metadata.estimated_ttft_saved_ms + 'ms | AST: ' + (data.metadata.ast_applied ? 'Applied' : 'Bypassed');
            }} catch (err) {{
                metadataPill.textContent = 'Error: ' + err.message;
            }} finally {{
                compressBtn.disabled = false;
                compressBtn.textContent = 'Compress Now';
            }}
        }});

        // Live WebSocket Telemetry Stream
        function setupWebSocket() {{
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const wsUrl = protocol + '//' + window.location.host + '/ws/telemetry';
            const ws = new WebSocket(wsUrl);

            ws.onopen = () => {{
                document.getElementById('wsStatusText').textContent = 'Live Connected';
            }};

            ws.onmessage = (event) => {{
                try {{
                    const msg = JSON.parse(event.data);
                    if (msg.event === 'new_request' && msg.record) {{
                        const r = msg.record;
                        const emptyRow = document.getElementById('emptyRow');
                        if (emptyRow) emptyRow.remove();

                        const red = Math.round((1 - r.compression_ratio) * 100);
                        const astBadge = r.ast_applied
                            ? '<span class="px-2 py-0.5 text-xs bg-cyan-950 text-cyan-400 border border-cyan-800 rounded">AST</span>'
                            : '<span class="text-slate-600">-</span>';
                        const streamBadge = r.streaming
                            ? '<span class="text-emerald-400 font-medium">SSE</span>'
                            : '<span class="text-slate-400">JSON</span>';

                        const tr = document.createElement('tr');
                        tr.className = 'border-b border-slate-800/60 hover:bg-slate-800/30 text-sm transition-colors new-row';
                        tr.innerHTML = `
                            <td class="py-3 px-4 font-mono text-xs text-slate-400">${{r.id.slice(0, 12)}}</td>
                            <td class="py-3 px-4 font-medium text-slate-300">${{r.model}}</td>
                            <td class="py-3 px-4">${{streamBadge}}</td>
                            <td class="py-3 px-4 font-mono">${{r.original_tokens.toLocaleString()}} &rarr; <span class="text-cyan-400">${{r.compacted_tokens.toLocaleString()}}</span></td>
                            <td class="py-3 px-4 font-semibold text-emerald-400">-${{red}}%</td>
                            <td class="py-3 px-4">${{astBadge}}</td>
                            <td class="py-3 px-4 font-mono text-xs text-slate-400">${{r.duration_ms}} ms</td>
                        `;
                        recentRowsTable.insertBefore(tr, recentRowsTable.firstChild);

                        // Increment KPI request count
                        const kpiReq = document.getElementById('kpiRequests');
                        if (kpiReq) {{
                            const cur = parseInt(kpiReq.textContent.replace(/,/g, ''), 10) || 0;
                            kpiReq.textContent = (cur + 1).toLocaleString();
                        }}
                    }}
                }} catch (e) {{}}
            }};

            ws.onclose = () => {{
                document.getElementById('wsStatusText').textContent = 'Disconnected';
                setTimeout(setupWebSocket, 3000);
            }};
        }}
        setupWebSocket();
    </script>
</body>
</html>"""
