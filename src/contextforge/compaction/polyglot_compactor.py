"""Polyglot AST and structural code compactor for TypeScript, JavaScript, Go, and Rust."""

import re
from typing import Dict, List, Optional, Set, Tuple
from contextforge.core.models import AstSummary
from contextforge.core.tokenizer import count_tokens


class PolyglotCompactor:
    """Structural compactor for TypeScript/JavaScript, Go, and Rust codeblocks."""

    def __init__(self, aggressive: bool = False):
        self.aggressive = aggressive

    def compact(
        self,
        code: str,
        language: str,
        keep_symbols: Optional[Set[str]] = None,
    ) -> Tuple[str, AstSummary]:
        """Compact code in the target programming language."""
        lang = language.lower().strip()
        symbols = keep_symbols or set()
        original_lines = len(code.splitlines())
        original_tokens = count_tokens(code)

        if lang in ("typescript", "ts", "javascript", "js", "tsx", "jsx"):
            compacted_code, summary = self._compact_typescript(code, symbols)
        elif lang in ("go", "golang"):
            compacted_code, summary = self._compact_go(code, symbols)
        elif lang in ("rust", "rs"):
            compacted_code, summary = self._compact_rust(code, symbols)
        else:
            compacted_code, summary = self._compact_generic(code, lang)

        return compacted_code, summary

    def _compact_typescript(self, code: str, keep_symbols: Set[str]) -> Tuple[str, AstSummary]:
        original_lines = len(code.splitlines())
        lines = code.splitlines()
        functions_skeletonized = 0
        docstrings_trimmed = 0
        imports_deduped = 0

        # Step 1: Deduplicate ES6 imports
        cleaned_lines: List[str] = []
        import_map: Dict[str, Set[str]] = {}
        in_import_block = False

        for line in lines:
            stripped = line.strip()
            # Match: import { a, b } from 'module';
            import_match = re.match(r"^import\s+\{\s*([^}]+)\s*\}\s+from\s+['\"]([^'\"]+)['\"];?", stripped)
            if import_match:
                names = [n.strip() for n in import_match.group(1).split(",") if n.strip()]
                mod = import_match.group(2)
                if mod not in import_map:
                    import_map[mod] = set()
                else:
                    imports_deduped += 1
                import_map[mod].update(names)
                continue
            cleaned_lines.append(line)

        # Prepend merged imports
        merged_import_lines = [
            f"import {{ {', '.join(sorted(names))} }} from '{mod}';"
            for mod, names in import_map.items()
        ]
        processed_code = "\n".join(merged_import_lines + cleaned_lines)

        # Step 2: Trim JSDoc comments
        def trim_jsdoc(match: re.Match) -> str:
            nonlocal docstrings_trimmed
            docstrings_trimmed += 1
            if self.aggressive:
                return ""
            doc = match.group(0)
            inner_lines = [l.strip().lstrip("/*").rstrip("*/").strip().lstrip("*").strip() for l in doc.splitlines()]
            summary_lines = [l for l in inner_lines if l]
            if summary_lines:
                return f"/** {summary_lines[0]} */"
            return ""

        processed_code = re.sub(r"/\*\*[\s\S]*?\*/", trim_jsdoc, processed_code)

        # Step 3: Skeletonize private helper functions (function helperName(...) { ... })
        def skeletonize_ts_func(match: re.Match) -> str:
            nonlocal functions_skeletonized
            fn_decl = match.group(1)
            fn_name = match.group(2)
            fn_body = match.group(3)

            is_pinned = fn_name in keep_symbols or any(s.lower() in fn_name.lower() for s in keep_symbols if len(s) >= 3)
            is_exported = "export" in fn_decl

            if not is_pinned and not is_exported and len(fn_body.strip().splitlines()) > 2:
                functions_skeletonized += 1
                return f"{fn_decl} {{ /* ... */ }}"
            return match.group(0)

        # Pattern: (function name(...): returnType) { body }
        processed_code = re.sub(
            r"((?:export\s+)?(?:async\s+)?function\s+([a-zA-Z0-9_$]+)\s*\([^)]*\)(?:\s*:\s*[^{]+)?)\s*\{([\s\S]*?\n\s*\})",
            skeletonize_ts_func,
            processed_code,
        )

        compacted_lines = len(processed_code.splitlines())
        reduction = round((1.0 - (compacted_lines / max(original_lines, 1))) * 100, 1)

        summary = AstSummary(
            language="typescript",
            original_lines=original_lines,
            compacted_lines=compacted_lines,
            functions_analyzed=functions_skeletonized + 1,
            functions_skeletonized=functions_skeletonized,
            docstrings_trimmed=docstrings_trimmed,
            imports_deduplicated=imports_deduped,
            reduction_percentage=max(0.0, reduction),
        )
        return processed_code.strip(), summary

    def _compact_go(self, code: str, keep_symbols: Set[str]) -> Tuple[str, AstSummary]:
        original_lines = len(code.splitlines())
        functions_skeletonized = 0

        # Skeletonize unexported functions: func helperName(...) ... { ... }
        def skeletonize_go_func(match: re.Match) -> str:
            nonlocal functions_skeletonized
            decl = match.group(1)
            name = match.group(2)
            body = match.group(3)

            is_exported = name[0].isupper() if name else False
            is_pinned = name in keep_symbols

            if not is_exported and not is_pinned and len(body.strip().splitlines()) > 2:
                functions_skeletonized += 1
                return f"{decl} {{\n\t// ...\n}}"
            return match.group(0)

        processed_code = re.sub(
            r"(func\s+(?:\([^)]+\)\s+)?([a-zA-Z0-9_]+)\s*\([^)]*\)[^{]*)\{([\s\S]*?\n\})",
            skeletonize_go_func,
            code,
        )

        compacted_lines = len(processed_code.splitlines())
        reduction = round((1.0 - (compacted_lines / max(original_lines, 1))) * 100, 1)

        summary = AstSummary(
            language="go",
            original_lines=original_lines,
            compacted_lines=compacted_lines,
            functions_analyzed=functions_skeletonized + 1,
            functions_skeletonized=functions_skeletonized,
            docstrings_trimmed=0,
            imports_deduplicated=0,
            reduction_percentage=max(0.0, reduction),
        )
        return processed_code.strip(), summary

    def _compact_rust(self, code: str, keep_symbols: Set[str]) -> Tuple[str, AstSummary]:
        original_lines = len(code.splitlines())
        functions_skeletonized = 0

        def skeletonize_rust_fn(match: re.Match) -> str:
            nonlocal functions_skeletonized
            decl = match.group(1)
            name = match.group(2)
            body = match.group(3)

            is_pub = "pub" in decl
            is_pinned = name in keep_symbols

            if not is_pub and not is_pinned and len(body.strip().splitlines()) > 2:
                functions_skeletonized += 1
                return f"{decl} {{\n    todo!()\n}}"
            return match.group(0)

        processed_code = re.sub(
            r"((?:pub\s+)?(?:async\s+)?fn\s+([a-zA-Z0-9_]+)\s*(?:<[^>]+>)?\s*\([^)]*\)[^{]*)\{([\s\S]*?\n\})",
            skeletonize_rust_fn,
            code,
        )

        compacted_lines = len(processed_code.splitlines())
        reduction = round((1.0 - (compacted_lines / max(original_lines, 1))) * 100, 1)

        summary = AstSummary(
            language="rust",
            original_lines=original_lines,
            compacted_lines=compacted_lines,
            functions_analyzed=functions_skeletonized + 1,
            functions_skeletonized=functions_skeletonized,
            docstrings_trimmed=0,
            imports_deduplicated=0,
            reduction_percentage=max(0.0, reduction),
        )
        return processed_code.strip(), summary

    def _compact_generic(self, code: str, language: str) -> Tuple[str, AstSummary]:
        lines = [line.rstrip() for line in code.splitlines()]
        cleaned = [l for l in lines if l]
        result = "\n".join(cleaned)
        original_lines = len(lines)
        compacted_lines = len(cleaned)
        reduction = round((1.0 - (compacted_lines / max(original_lines, 1))) * 100, 1)

        return result, AstSummary(
            language=language,
            original_lines=original_lines,
            compacted_lines=compacted_lines,
            functions_analyzed=0,
            functions_skeletonized=0,
            docstrings_trimmed=0,
            imports_deduplicated=0,
            reduction_percentage=max(0.0, reduction),
        )
