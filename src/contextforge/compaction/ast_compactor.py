"""Authentic AST-based code compactor for Python and polyglot code structures."""

import ast
import re
from typing import Any, Dict, List, Optional, Set, Tuple
from contextforge.compaction.base import BaseCompactor, CompactionResult, CompactorContext
from contextforge.core.models import AstSummary
from contextforge.core.tokenizer import count_tokens

# Regex to match markdown code fences: ```language \n code \n ```
CODE_FENCE_REGEX = re.compile(r"(```([a-zA-Z0-9_\-\.\+]*)\n(.*?)```)", re.DOTALL)


class PythonAstTransformer(ast.NodeTransformer):
    """AST Transformer that prunes docstrings and skeletonizes non-critical function bodies."""

    def __init__(
        self,
        keep_symbols: Set[str],
        aggressive: bool = False,
        compact_docstrings: bool = True,
        skeletonize_helpers: bool = True,
    ):
        self.keep_symbols = keep_symbols
        self.aggressive = aggressive
        self.compact_docstrings = compact_docstrings
        self.skeletonize_helpers = skeletonize_helpers

        # Telemetry metrics
        self.functions_analyzed = 0
        self.functions_skeletonized = 0
        self.docstrings_trimmed = 0

    def _trim_docstring(self, node: ast.AST) -> None:
        """Trim or compact the leading docstring of a module, class, or function."""
        if not self.compact_docstrings:
            return
        if not hasattr(node, "body") or not node.body:
            return

        first_stmt = node.body[0]
        if (
            isinstance(first_stmt, ast.Expr)
            and isinstance(first_stmt.value, ast.Constant)
            and isinstance(first_stmt.value.value, str)
        ):
            doc = first_stmt.value.value.strip()
            if not doc:
                return

            if self.aggressive:
                # In aggressive mode, remove docstring entirely
                node.body.pop(0)
                self.docstrings_trimmed += 1
            else:
                # Keep only first sentence / summary line
                first_line = doc.split("\n")[0].strip()
                if len(doc.split("\n")) > 1 or len(doc) > len(first_line):
                    first_stmt.value.value = first_line
                    self.docstrings_trimmed += 1

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.AST:
        self._trim_docstring(node)
        self.generic_visit(node)
        return node

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        return self._process_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
        return self._process_function(node)

    def _process_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> ast.AST:
        self.functions_analyzed += 1
        name = node.name

        # Check if function is prioritized
        is_pinned = (
            name in self.keep_symbols
            or any(s.lower() in name.lower() for s in self.keep_symbols if len(s) >= 3)
            or name.startswith("__init__")
            or name.startswith("__call__")
        )

        self._trim_docstring(node)

        # If not pinned and skeletonization is requested
        if self.skeletonize_helpers and not is_pinned:
            # Check length of function body
            original_body_len = len(node.body)
            if original_body_len > 1:
                # Create ellipsis expression statement: ...
                ellipsis_stmt = ast.Expr(
                    value=ast.Constant(value=Ellipsis),
                    lineno=node.lineno,
                    col_offset=node.col_offset + 4,
                )
                node.body = [ellipsis_stmt]
                self.functions_skeletonized += 1
                return node

        self.generic_visit(node)
        return node


class PythonCompactor:
    """Authentic AST compaction for Python source code."""

    def compact(
        self,
        code: str,
        keep_symbols: Set[str],
        aggressive: bool = False,
    ) -> Tuple[str, AstSummary]:
        original_lines = len(code.splitlines())
        original_tokens = count_tokens(code)

        try:
            tree = ast.parse(code)
        except SyntaxError:
            # If not a complete valid module, return clean normalized code
            clean_code = self._clean_comments_and_blank_lines(code)
            summary = AstSummary(
                language="python",
                original_lines=original_lines,
                compacted_lines=len(clean_code.splitlines()),
                functions_analyzed=0,
                functions_skeletonized=0,
                docstrings_trimmed=0,
                imports_deduplicated=0,
                reduction_percentage=0.0,
            )
            return clean_code, summary

        # Deduplicate and sort top-level imports
        tree, imports_deduped = self._deduplicate_imports(tree)

        # Run AST transformer
        transformer = PythonAstTransformer(
            keep_symbols=keep_symbols,
            aggressive=aggressive,
            compact_docstrings=True,
            skeletonize_helpers=True,
        )
        transformed_tree = transformer.visit(tree)
        ast.fix_missing_locations(transformed_tree)

        # Unparse AST back to syntactically valid Python code
        try:
            compacted_code = ast.unparse(transformed_tree)
        except Exception:
            compacted_code = code

        # Clean trailing whitespace and unnecessary multi-newlines
        compacted_code = self._clean_comments_and_blank_lines(compacted_code)
        compacted_lines = len(compacted_code.splitlines())
        compacted_tokens = count_tokens(compacted_code)

        reduction = 0.0
        if original_tokens > 0:
            reduction = round(
                max(0.0, (original_tokens - compacted_tokens) / original_tokens * 100), 2
            )

        summary = AstSummary(
            language="python",
            original_lines=original_lines,
            compacted_lines=compacted_lines,
            functions_analyzed=transformer.functions_analyzed,
            functions_skeletonized=transformer.functions_skeletonized,
            docstrings_trimmed=transformer.docstrings_trimmed,
            imports_deduplicated=imports_deduped,
            reduction_percentage=reduction,
        )
        return compacted_code, summary

    def _deduplicate_imports(self, tree: ast.AST) -> Tuple[ast.AST, int]:
        """Combine duplicate 'from x import y' imports and eliminate duplicates."""
        new_body: List[ast.stmt] = []
        from_imports: Dict[Tuple[str, int], Set[Tuple[str, Optional[str]]]] = {}
        regular_imports: Set[Tuple[str, Optional[str]]] = set()
        dedup_count = 0

        for stmt in tree.body:
            if isinstance(stmt, ast.ImportFrom):
                module = stmt.module or ""
                level = stmt.level
                key = (module, level)
                if key not in from_imports:
                    from_imports[key] = set()
                for alias in stmt.names:
                    pair = (alias.name, alias.asname)
                    if pair in from_imports[key]:
                        dedup_count += 1
                    else:
                        from_imports[key].add(pair)
            elif isinstance(stmt, ast.Import):
                for alias in stmt.names:
                    pair = (alias.name, alias.asname)
                    if pair in regular_imports:
                        dedup_count += 1
                    else:
                        regular_imports.add(pair)
            else:
                new_body.append(stmt)

        # Reconstruct consolidated imports at the top
        reconstructed_imports: List[ast.stmt] = []
        for name, asname in sorted(regular_imports):
            reconstructed_imports.append(ast.Import(names=[ast.alias(name=name, asname=asname)]))

        for (module, level), aliases in sorted(from_imports.items()):
            alias_nodes = [
                ast.alias(name=n, asname=a) for n, a in sorted(aliases, key=lambda x: x[0])
            ]
            reconstructed_imports.append(
                ast.ImportFrom(module=module or None, names=alias_nodes, level=level)
            )

        tree.body = reconstructed_imports + new_body
        return tree, dedup_count

    def _clean_comments_and_blank_lines(self, code: str) -> str:
        """Strip decorative comment dividers and collapse 3+ empty lines into 1."""
        lines = code.splitlines()
        cleaned: List[str] = []
        blank_counter = 0

        for line in lines:
            stripped = line.strip()
            # Strip pure divider comments like # ---------------- or # ================
            if stripped.startswith("#") and len(stripped) >= 10:
                inner = stripped[1:].strip()
                if set(inner) in ({'-'}, {'='}, {'*'}, {'#'}):
                    continue

            if not stripped:
                blank_counter += 1
                if blank_counter <= 1:
                    cleaned.append("")
            else:
                blank_counter = 0
                cleaned.append(line)

        return "\n".join(cleaned)


class PolyglotStructuralCompactor:
    """Structural compactor for TypeScript, JavaScript, Go, Rust, and C-like syntaxes."""

    def compact(
        self,
        code: str,
        language: str,
        keep_symbols: Set[str],
        aggressive: bool = False,
    ) -> Tuple[str, AstSummary]:
        original_lines = len(code.splitlines())
        original_tokens = count_tokens(code)

        lines = code.splitlines()
        output_lines: List[str] = []
        in_block_comment = False
        inside_function_body = False
        current_indent = 0
        functions_analyzed = 0
        functions_skeletonized = 0

        # Pattern matching function or method declarations in JS/TS/Go/Rust
        func_sig_pattern = re.compile(
            r"^\s*(?:export\s+)?(?:async\s+)?(?:function|func|fn|def)\s+([a-zA-Z0-9_]+)\b|"
            r"^\s*(?:public|private|protected|async|\s)*([a-zA-Z0-9_]+)\s*\([^)]*\)\s*(?::\s*[^\{]+)?\s*\{"
        )

        for line in lines:
            stripped = line.strip()

            # Handle block comments
            if "/*" in stripped:
                in_block_comment = True
            if "*/" in stripped:
                in_block_comment = False
                continue
            if in_block_comment:
                continue

            # Strip decorative dividers
            if stripped.startswith("//") and len(stripped) > 10:
                inner = stripped[2:].strip()
                if set(inner) in ({'-'}, {'='}, {'*'}, {'/'}):
                    continue

            # Check for function start
            match = func_sig_pattern.search(line)
            if match and "{" in line:
                name = match.group(1) or match.group(2)
                functions_analyzed += 1
                is_pinned = (
                    name in keep_symbols
                    or any(s.lower() in name.lower() for s in keep_symbols if len(s) >= 3)
                    or aggressive is False
                )

                if aggressive and not is_pinned and not inside_function_body:
                    # Elide body
                    head = line[: line.index("{") + 1]
                    output_lines.append(f"{head} /* elided */ }}")
                    functions_skeletonized += 1
                    continue

            output_lines.append(line)

        compacted = "\n".join(output_lines)
        compacted_tokens = count_tokens(compacted)
        reduction = 0.0
        if original_tokens > 0:
            reduction = round(
                max(0.0, (original_tokens - compacted_tokens) / original_tokens * 100), 2
            )

        summary = AstSummary(
            language=language or "polyglot",
            original_lines=original_lines,
            compacted_lines=len(output_lines),
            functions_analyzed=functions_analyzed,
            functions_skeletonized=functions_skeletonized,
            docstrings_trimmed=0,
            imports_deduplicated=0,
            reduction_percentage=reduction,
        )
        return compacted, summary


class AstCompactor(BaseCompactor):
    """High-level AST and code compaction engine that processes markdown fences or raw code."""

    def __init__(self):
        self.python_compactor = PythonCompactor()
        self.polyglot_compactor = PolyglotStructuralCompactor()

    def compact(self, text: str, context: CompactorContext) -> CompactionResult:
        original_tokens = count_tokens(text)
        if not text:
            return CompactionResult(
                compacted_text="",
                original_tokens=0,
                compacted_tokens=0,
                tokens_saved=0,
                compression_ratio=1.0,
                metadata={"ast_applied": False},
            )

        keep_symbols = self._extract_salient_symbols(context)
        is_aggressive = context.strategy == "aggressive" or context.target_ratio <= 0.40

        # Check if entire text is a Python file
        if self._is_pure_python(text):
            compacted, summary = self.python_compactor.compact(
                text, keep_symbols=keep_symbols, aggressive=is_aggressive
            )
            compacted_tokens = count_tokens(compacted)
            return CompactionResult(
                compacted_text=compacted,
                original_tokens=original_tokens,
                compacted_tokens=compacted_tokens,
                tokens_saved=max(0, original_tokens - compacted_tokens),
                compression_ratio=round(compacted_tokens / max(1, original_tokens), 4),
                metadata={
                    "ast_applied": True,
                    "ast_summaries": [summary.model_dump()],
                },
            )

        # Process markdown fences if present
        summaries: List[AstSummary] = []

        def replace_fence(match: re.Match) -> str:
            full_fence = match.group(1)
            lang = (match.group(2) or "").lower()
            code_body = match.group(3)

            if not code_body.strip():
                return full_fence

            if lang in ("python", "py"):
                comp_code, summary = self.python_compactor.compact(
                    code_body, keep_symbols=keep_symbols, aggressive=is_aggressive
                )
                summaries.append(summary)
                return f"```{lang}\n{comp_code}\n```"
            elif lang in ("javascript", "typescript", "js", "ts", "go", "rust", "rs"):
                comp_code, summary = self.polyglot_compactor.compact(
                    code_body, language=lang, keep_symbols=keep_symbols, aggressive=is_aggressive
                )
                summaries.append(summary)
                return f"```{lang}\n{comp_code}\n```"
            return full_fence

        compacted_text = CODE_FENCE_REGEX.sub(replace_fence, text)
        compacted_tokens = count_tokens(compacted_text)

        return CompactionResult(
            compacted_text=compacted_text,
            original_tokens=original_tokens,
            compacted_tokens=compacted_tokens,
            tokens_saved=max(0, original_tokens - compacted_tokens),
            compression_ratio=round(compacted_tokens / max(1, original_tokens), 4),
            metadata={
                "ast_applied": len(summaries) > 0,
                "ast_summaries": [s.model_dump() for s in summaries],
            },
        )

    def _is_pure_python(self, text: str) -> bool:
        """Heuristic to check if text is raw Python without markdown wrapper."""
        if "```" in text:
            return False
        try:
            tree = ast.parse(text)
            return len(tree.body) > 0
        except SyntaxError:
            return False

    def _extract_salient_symbols(self, context: CompactorContext) -> Set[str]:
        """Extract prioritized symbol names from pinned set and query context."""
        symbols: Set[str] = set(context.pinned_symbols)
        if context.query_context:
            # Match identifier-like words in query
            words = re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]{2,}\b", context.query_context)
            for w in words:
                symbols.add(w)
        return symbols
