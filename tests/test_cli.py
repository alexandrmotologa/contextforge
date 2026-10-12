"""Unit tests for the Typer command-line interface."""

from typer.testing import CliRunner
from contextforge.cli.main import app

runner = CliRunner()


def test_cli_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "ContextForge" in result.output
    assert "serve" in result.output
    assert "compress" in result.output
    assert "benchmark" in result.output
    assert "stats" in result.output


def test_cli_compress_text():
    sample_text = """
def calculation_one():
    return 42

def helper_internal():
    a = 1
    b = 2
    return a + b
"""
    result = runner.invoke(app, ["compress", sample_text, "--strategy", "aggressive", "--ratio", "0.4"])
    assert result.exit_code == 0
    assert "Original Tokens" in result.output
    assert "Compacted Tokens" in result.output


def test_cli_benchmark():
    result = runner.invoke(app, ["benchmark"])
    assert result.exit_code == 0
    assert "Preset Benchmarks" in result.output
    assert "Balanced" in result.output
    assert "Aggressive" in result.output


def test_cli_stats(tmp_path):
    test_db = tmp_path / "cli_test.db"
    result = runner.invoke(app, ["stats", "--db", str(test_db)])
    assert result.exit_code == 0
    assert "Lifetime Statistics" in result.output
    assert "Total Proxied Requests" in result.output


def test_cli_compress_file_input_and_output(tmp_path):
    input_file = tmp_path / "sample.py"
    output_file = tmp_path / "compacted.py"
    input_file.write_text("def test_func():\n    '''Detailed docstring.'''\n    return 100\n", encoding="utf-8")

    result = runner.invoke(
        app,
        ["compress", str(input_file), "--output", str(output_file), "--strategy", "aggressive"],
    )
    assert result.exit_code == 0
    assert output_file.exists()
    assert "Compacted text written to" in result.output

