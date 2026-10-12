"""Unit tests for AST-based code compaction engine."""

import ast
import pytest
from contextforge.compaction.ast_compactor import AstCompactor, PythonCompactor
from contextforge.compaction.base import CompactorContext


def test_python_ast_compactor_deduplicates_imports():
    code = """
from os import path
import sys
from os import getcwd
from os import path
import sys

def run():
    print("running")
"""
    compactor = PythonCompactor()
    compacted, summary = compactor.compact(code, keep_symbols={"run"}, aggressive=False)

    # Output should be valid python
    parsed = ast.parse(compacted)
    assert parsed is not None
    assert summary.imports_deduplicated >= 2
    assert "from os import getcwd, path" in compacted or ("getcwd" in compacted and "path" in compacted)


def test_python_ast_compactor_skeletonizes_unrelated_functions():
    code = """
def critical_calculation(x: int) -> int:
    \"\"\"This is a critical function that calculates important values.\"\"\"
    step1 = x * 2
    step2 = step1 + 42
    return step2

def internal_helper_one():
    \"\"\"Helper one implementation details.\"\"\"
    a = 1
    b = 2
    c = a + b
    return c

def internal_helper_two():
    \"\"\"Helper two implementation details.\"\"\"
    x = [i for i in range(100)]
    return len(x)
"""
    compactor = AstCompactor()
    ctx = CompactorContext(
        strategy="aggressive",
        target_ratio=0.3,
        query_context="How does critical_calculation work?",
        pinned_symbols={"critical_calculation"},
    )

    result = compactor.compact(code, ctx)
    assert result.original_tokens > result.compacted_tokens
    assert result.tokens_saved > 0
    assert result.metadata["ast_applied"] is True

    # Check that critical_calculation retained its implementation
    assert "critical_calculation" in result.compacted_text
    assert "step2 = step1 + 42" in result.compacted_text

    # Check that helpers were skeletonized with ...
    assert "..." in result.compacted_text

    # Verify that the output is syntactically valid Python code
    parsed = ast.parse(result.compacted_text)
    assert parsed is not None


def test_markdown_fence_compaction():
    markdown_doc = """
# System Architecture

Here is the helper script:

```python
import os
import os

def helper_one():
    \"\"\"Verbose helper docstring line 1
    Verbose helper docstring line 2
    Verbose helper docstring line 3
    \"\"\"
    temp = 100
    temp2 = temp * 20
    return temp2

def main():
    return helper_one()
```

End of document.
"""
    compactor = AstCompactor()
    ctx = CompactorContext(
        strategy="aggressive",
        target_ratio=0.4,
        query_context="How does main work?",
        pinned_symbols={"main"},
    )

    res = compactor.compact(markdown_doc, ctx)
    assert "```python" in res.compacted_text
    assert res.compacted_tokens < res.original_tokens
    assert res.metadata["ast_applied"] is True


def test_python_ast_class_and_docstrings():
    code = """
class DataWorker:
    \"\"\"Worker class that performs heavy processing.
    Here is an extended explanation of the worker.
    \"\"\"

    def __init__(self, name: str):
        self.name = name

    def compute(self):
        \"\"\"Compute summary values.\"\"\"
        return 42

    def unimportant_helper(self):
        \"\"\"Helper method.\"\"\"
        a = 1
        b = 2
        return a + b
"""
    compactor = PythonCompactor()
    compacted, summary = compactor.compact(code, keep_symbols={"compute"}, aggressive=False)
    assert "class DataWorker:" in compacted
    assert "def compute" in compacted
    assert summary.docstrings_trimmed >= 1


def test_python_ast_syntax_error_fallback():
    code = "def invalid_syntax(x: int\n   missing_colon = 1\n"
    compactor = PythonCompactor()
    compacted, summary = compactor.compact(code, keep_symbols=set())
    assert summary.functions_analyzed == 0
    assert "missing_colon" in compacted


def test_polyglot_markdown_fence_compaction():
    markdown_doc = """
```javascript
// A sample JavaScript block
function calculateTotal(items) {
    let sum = 0;
    // loop through items
    for (let i = 0; i < items.length; i++) {
        sum += items[i];
    }
    return sum;
}
```
"""
    compactor = AstCompactor()
    ctx = CompactorContext(strategy="aggressive")
    res = compactor.compact(markdown_doc, ctx)
    assert "calculateTotal" in res.compacted_text

