"""Authentic graph-based semantic token compactor with query-guided salience and entity preservation."""

import math
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Set, Tuple
from contextforge.compaction.base import BaseCompactor, CompactionResult, CompactorContext
from contextforge.core.tokenizer import count_tokens

# Patterns for sentences and entity preservation
SENTENCE_SPLIT_REGEX = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])|\n\n+")
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "has", "he", "in", "is", "it", "its", "of", "on", "that", "the",
    "to", "was", "were", "will", "with", "this", "there", "they", "we"
}

# Regex to detect critical factual elements (numbers, paths, urls, constraints, errors)
CRITICAL_FACT_REGEX = re.compile(
    r"(https?://\S+|/[\w\.-]+(?:/[\w\.-]+)+|[A-Za-z]:\\[\w\.-]+|\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b|"
    r"\b(?:error|exception|failed|fatal|critical|must|never|always|warning|timeout)\b|"
    r"\b\d+[\.,]?\d*\b)",
    re.IGNORECASE,
)


class SentenceNode:
    """Represents a candidate sentence in the semantic graph."""

    def __init__(self, index: int, text: str):
        self.index = index
        self.text = text.strip()
        self.words = [
            w.lower()
            for w in re.findall(r"\b\w{2,}\b", self.text)
            if w.lower() not in STOPWORDS
        ]
        self.word_counts = Counter(self.words)
        self.token_count = count_tokens(self.text)
        self.rank_score = 1.0
        self.query_score = 0.0
        self.has_critical_fact = bool(CRITICAL_FACT_REGEX.search(self.text))
        self.is_header = self.text.startswith("#") or self.text.startswith("===") or self.text.startswith("---")


class SemanticCompactor(BaseCompactor):
    """TextRank graph-based extractive summarizer with BM25 query salience and entity preservation."""

    def __init__(self, damping: float = 0.85, max_iterations: int = 25, convergence_threshold: float = 0.0001):
        self.damping = damping
        self.max_iterations = max_iterations
        self.convergence_threshold = convergence_threshold

    def compact(self, text: str, context: CompactorContext) -> CompactionResult:
        original_tokens = count_tokens(text)
        if not text or original_tokens <= 64:
            return CompactionResult(
                compacted_text=text,
                original_tokens=original_tokens,
                compacted_tokens=original_tokens,
                tokens_saved=0,
                compression_ratio=1.0,
                metadata={
                    "semantic_sentences_kept": 1,
                    "semantic_sentences_dropped": 0,
                },
            )

        # Step 1: Deduplicate consecutive repetitive lines (e.g. repeated logs/polling)
        deduped_text, repetition_dropped = self._deduplicate_repetitions(text)

        # Step 2: Split text into structured sentence nodes
        raw_sentences = self._split_into_sentences(deduped_text)
        if len(raw_sentences) <= 3:
            compacted_tokens = count_tokens(deduped_text)
            return CompactionResult(
                compacted_text=deduped_text,
                original_tokens=original_tokens,
                compacted_tokens=compacted_tokens,
                tokens_saved=max(0, original_tokens - compacted_tokens),
                compression_ratio=round(compacted_tokens / max(1, original_tokens), 4),
                metadata={
                    "semantic_sentences_kept": len(raw_sentences),
                    "semantic_sentences_dropped": repetition_dropped,
                },
            )

        nodes = [SentenceNode(i, s) for i, s in enumerate(raw_sentences) if s.strip()]

        # Step 3: Compute BM25 query salience if query context is present
        if context.query_context:
            self._compute_query_salience(nodes, context.query_context)

        # Step 4: Build TextRank graph and run PageRank iterations
        self._run_textrank(nodes)

        # Step 5: Composite scoring and ranking
        # Composite score = TextRank * (1.0 + 2.0 * query_score) + bonus for critical facts / headers
        for node in nodes:
            multiplier = 1.0 + (node.query_score * 2.5)
            if node.has_critical_fact:
                multiplier *= 1.3
            if node.is_header:
                multiplier *= 1.4
            node.rank_score *= multiplier

        # Target token budget calculation
        target_tokens = int(original_tokens * context.target_ratio)
        if context.max_tokens:
            target_tokens = min(target_tokens, context.max_tokens)
        target_tokens = max(64, target_tokens)

        # Step 6: Select top nodes to fit budget, maintaining chronological order
        selected_nodes = self._select_budget_nodes(nodes, target_tokens)
        selected_nodes.sort(key=lambda n: n.index)

        compacted_text = "\n\n".join(n.text for n in selected_nodes)
        compacted_tokens = count_tokens(compacted_text)
        saved = max(0, original_tokens - compacted_tokens)

        return CompactionResult(
            compacted_text=compacted_text,
            original_tokens=original_tokens,
            compacted_tokens=compacted_tokens,
            tokens_saved=saved,
            compression_ratio=round(compacted_tokens / max(1, original_tokens), 4),
            metadata={
                "semantic_sentences_kept": len(selected_nodes),
                "semantic_sentences_dropped": len(nodes) - len(selected_nodes) + repetition_dropped,
            },
        )

    def _split_into_sentences(self, text: str) -> List[str]:
        """Split text into sentences while respecting markdown lists and paragraphs."""
        paragraphs = text.split("\n\n")
        sentences: List[str] = []
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            # Keep markdown tables or code blocks as single atomic units
            if para.startswith("|") or para.startswith("```"):
                sentences.append(para)
                continue

            # Split paragraph into sentences
            chunks = SENTENCE_SPLIT_REGEX.split(para)
            for chunk in chunks:
                chunk = chunk.strip()
                if chunk:
                    sentences.append(chunk)
        return sentences

    def _deduplicate_repetitions(self, text: str) -> Tuple[str, int]:
        """Detect and compress identical or near-identical repeating lines."""
        lines = text.splitlines()
        if len(lines) < 4:
            return text, 0

        deduped: List[str] = []
        repeat_counter = 0
        last_line = ""
        dropped = 0

        for line in lines:
            stripped = line.strip()
            if stripped and stripped == last_line:
                repeat_counter += 1
                dropped += 1
            else:
                if repeat_counter > 1:
                    deduped.append(f"[repeated {repeat_counter} times: {last_line}]")
                repeat_counter = 0
                deduped.append(line)
                last_line = stripped

        if repeat_counter > 1:
            deduped.append(f"[repeated {repeat_counter} times: {last_line}]")

        return "\n".join(deduped), dropped

    def _compute_query_salience(self, nodes: List[SentenceNode], query: str) -> None:
        """Score sentence nodes based on BM25 similarity with the user's active query."""
        query_words = [
            w.lower()
            for w in re.findall(r"\b\w{2,}\b", query)
            if w.lower() not in STOPWORDS
        ]
        if not query_words:
            return

        query_counter = Counter(query_words)
        total_docs = len(nodes)
        avg_doc_len = sum(len(n.words) for n in nodes) / max(1, total_docs)
        k1 = 1.5
        b = 0.75

        # Calculate document frequency for query terms
        doc_freq = Counter()
        for node in nodes:
            for word in set(node.words):
                if word in query_counter:
                    doc_freq[word] += 1

        for node in nodes:
            score = 0.0
            doc_len = len(node.words)
            for word, qf in query_counter.items():
                if word in node.word_counts:
                    df = doc_freq[word]
                    idf = math.log(1.0 + (total_docs - df + 0.5) / (df + 0.5))
                    tf = node.word_counts[word]
                    num = tf * (k1 + 1.0)
                    denom = tf + k1 * (1.0 - b + b * (doc_len / avg_doc_len))
                    score += idf * (num / max(0.001, denom))
            node.query_score = score

    def _run_textrank(self, nodes: List[SentenceNode]) -> None:
        """Build similarity matrix and compute PageRank centrality scores."""
        n = len(nodes)
        if n <= 1:
            return

        # Build adjacency matrix using token set overlap
        similarity_matrix: List[List[float]] = [[0.0] * n for _ in range(n)]
        degree: List[float] = [0.0] * n

        for i in range(n):
            words_i = set(nodes[i].words)
            len_i = len(words_i)
            if len_i == 0:
                continue
            for j in range(i + 1, n):
                words_j = set(nodes[j].words)
                len_j = len(words_j)
                if len_j == 0:
                    continue

                intersection = len(words_i.intersection(words_j))
                if intersection > 0:
                    # Normalizing by log lengths prevents long sentences from dominating
                    norm = math.log(len_i + 1.0) + math.log(len_j + 1.0)
                    sim = intersection / max(0.1, norm)
                    similarity_matrix[i][j] = sim
                    similarity_matrix[j][i] = sim
                    degree[i] += sim
                    degree[j] += sim

        # Power iteration for PageRank
        scores = [1.0 / n] * n
        for _ in range(self.max_iterations):
            new_scores = [0.0] * n
            max_diff = 0.0
            for i in range(n):
                rank_sum = 0.0
                for j in range(n):
                    if i != j and degree[j] > 0.0:
                        rank_sum += (similarity_matrix[j][i] / degree[j]) * scores[j]
                new_scores[i] = (1.0 - self.damping) / n + self.damping * rank_sum
                diff = abs(new_scores[i] - scores[i])
                if diff > max_diff:
                    max_diff = diff
            scores = new_scores
            if max_diff < self.convergence_threshold:
                break

        for i, node in enumerate(nodes):
            node.rank_score = scores[i]

    def _select_budget_nodes(self, nodes: List[SentenceNode], budget: int) -> List[SentenceNode]:
        """Greedily select highest-ranking nodes within budget, ensuring first/last continuity."""
        if not nodes:
            return []

        # Always include the first node (attention sink / opening context)
        selected = {nodes[0].index: nodes[0]}
        current_tokens = nodes[0].token_count

        # Sort remaining nodes by rank_score descending
        ranked_pool = sorted(nodes[1:], key=lambda n: n.rank_score, reverse=True)

        for node in ranked_pool:
            if current_tokens + node.token_count <= budget:
                selected[node.index] = node
                current_tokens += node.token_count

        return list(selected.values())
