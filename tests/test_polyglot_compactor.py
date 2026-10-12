"""Unit tests for the PolyglotCompactor (TypeScript, Go, Rust)."""

import pytest
from contextforge.compaction.polyglot_compactor import PolyglotCompactor


def test_typescript_import_merging_and_jsdoc():
    compactor = PolyglotCompactor(aggressive=False)
    ts_code = """
import { useState } from 'react';
import { useEffect } from 'react';

/**
 * Calculates sum of two numbers with detailed documentation.
 * Extended notes here.
 */
function calculateSum(a: number, b: number): number {
    return a + b;
}

function internalHelper(): void {
    const x = 1;
    const y = 2;
    console.log(x + y);
}
"""
    compacted, summary = compactor.compact(ts_code, language="typescript", keep_symbols={"calculateSum"})
    assert "import { useEffect, useState } from 'react';" in compacted
    assert "calculateSum" in compacted
    assert "internalHelper" in compacted
    assert "/* ... */" in compacted
    assert summary.imports_deduplicated >= 1


def test_go_unexported_function_skeletonization():
    compactor = PolyglotCompactor()
    go_code = """
package main

import "fmt"

func ProcessPublicTask(name string) error {
    fmt.Println(name)
    return nil
}

func internalUnexportedHelper() int {
    a := 10
    b := 20
    c := 30
    return a + b + c
}
"""
    compacted, summary = compactor.compact(go_code, language="go", keep_symbols={"ProcessPublicTask"})
    assert "ProcessPublicTask" in compacted
    assert "fmt.Println(name)" in compacted
    assert "// ..." in compacted
    assert summary.functions_skeletonized >= 1


def test_rust_private_fn_skeletonization():
    compactor = PolyglotCompactor()
    rust_code = """
pub fn public_entrypoint() -> u32 {
    let result = 42;
    result
}

fn private_helper() -> bool {
    let step1 = true;
    let step2 = false;
    step1 && step2
}
"""
    compacted, summary = compactor.compact(rust_code, language="rust", keep_symbols={"public_entrypoint"})
    assert "pub fn public_entrypoint" in compacted
    assert "42" in compacted
    assert "todo!()" in compacted
    assert summary.functions_skeletonized >= 1
