"""Prometheus metrics exporter for ContextForge reverse proxy telemetry."""

import threading
from typing import Dict


class PrometheusMetrics:
    """Thread-safe Prometheus metrics collector and text generator."""

    def __init__(self):
        self._lock = threading.Lock()
        self.requests_total = 0
        self.tokens_original_total = 0
        self.tokens_saved_total = 0
        self.ttft_saved_seconds_total = 0.0
        self.failovers_total = 0
        self.model_requests: Dict[str, int] = {}

    def record_request(
        self,
        model: str,
        original_tokens: int,
        tokens_saved: int,
        ttft_saved_seconds: float,
        failover_occurred: bool = False,
    ) -> None:
        """Record telemetry for a completed proxy request."""
        with self._lock:
            self.requests_total += 1
            self.tokens_original_total += original_tokens
            self.tokens_saved_total += tokens_saved
            self.ttft_saved_seconds_total += ttft_saved_seconds
            if failover_occurred:
                self.failovers_total += 1
            self.model_requests[model] = self.model_requests.get(model, 0) + 1

    def generate_metrics_text(self) -> str:
        """Render standard Prometheus exposition format."""
        with self._lock:
            avg_ratio = (
                (self.tokens_original_total - self.tokens_saved_total) / max(1, self.tokens_original_total)
                if self.tokens_original_total > 0
                else 1.0
            )

            lines = [
                "# HELP contextforge_requests_total Total number of proxied chat completion requests.",
                "# TYPE contextforge_requests_total counter",
                f"contextforge_requests_total {self.requests_total}",
                "",
                "# HELP contextforge_tokens_original_total Cumulative prompt tokens received prior to compaction.",
                "# TYPE contextforge_tokens_original_total counter",
                f"contextforge_tokens_original_total {self.tokens_original_total}",
                "",
                "# HELP contextforge_tokens_saved_total Cumulative prompt tokens saved via compaction.",
                "# TYPE contextforge_tokens_saved_total counter",
                f"contextforge_tokens_saved_total {self.tokens_saved_total}",
                "",
                "# HELP contextforge_ttft_saved_seconds_total Cumulative estimated GPU prefill latency saved in seconds.",
                "# TYPE contextforge_ttft_saved_seconds_total counter",
                f"contextforge_ttft_saved_seconds_total {round(self.ttft_saved_seconds_total, 3)}",
                "",
                "# HELP contextforge_compression_ratio Average token retention ratio.",
                "# TYPE contextforge_compression_ratio gauge",
                f"contextforge_compression_ratio {round(avg_ratio, 4)}",
                "",
                "# HELP contextforge_upstream_failovers_total Total number of requests redirected to fallback upstreams.",
                "# TYPE contextforge_upstream_failovers_total counter",
                f"contextforge_upstream_failovers_total {self.failovers_total}",
            ]

            if self.model_requests:
                lines.append("")
                lines.append("# HELP contextforge_model_requests_total Requests proxied per model.")
                lines.append("# TYPE contextforge_model_requests_total counter")
                for m, count in sorted(self.model_requests.items()):
                    clean_model = m.replace('"', '\\"')
                    lines.append(f'contextforge_model_requests_total{{model="{clean_model}"}} {count}')

            lines.append("")
            return "\n".join(lines)


# Global singleton instance
metrics = PrometheusMetrics()
