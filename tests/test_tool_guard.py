"""Unit tests for the ToolGuard function calling and schema shield."""

import pytest
from contextforge.compaction.tool_guard import ToolGuard
from contextforge.core.models import ChatMessage


def test_tool_guard_identifies_tool_messages():
    guard = ToolGuard(enabled=True)

    normal_msg = ChatMessage(role="user", content="Hello world")
    assert guard.is_protected_message(normal_msg) is False

    tool_msg = ChatMessage(role="tool", content="{'result': 42}", tool_call_id="call_123")
    assert guard.is_protected_message(tool_msg) is True

    msg_with_calls = ChatMessage(
        role="assistant",
        content="I will call the search tool",
        tool_calls=[{"id": "c1", "type": "function", "function": {"name": "search", "arguments": "{}"}}],
    )
    assert guard.is_protected_message(msg_with_calls) is True


def test_tool_guard_shields_and_restores_xml_tools():
    guard = ToolGuard(enabled=True)
    raw_prompt = """
You are a helpful assistant with access to the following tools:
<tools>
<tool_def>
  <name>get_weather</name>
  <parameters>
    <location type="string" required="true" />
  </parameters>
</tool_def>
</tools>

Please query the weather for Bucharest.
"""
    shielded, mapping = guard.shield_text(raw_prompt)
    assert "<tools>" not in shielded
    assert "__CF_TOOL_GUARD_" in shielded
    assert len(mapping) == 1

    # Simulate some text transformation
    transformed = shielded.replace("Bucharest", "Cluj")

    restored = guard.unshield_text(transformed, mapping)
    assert "<tools>" in restored
    assert "<name>get_weather</name>" in restored
    assert "Cluj" in restored


def test_tool_guard_shields_json_schema():
    guard = ToolGuard(enabled=True)
    raw_prompt = """
Here is the strict JSON schema:
```json
{
  "type": "object",
  "properties": {
    "user_id": {"type": "integer"},
    "role": {"type": "string"}
  },
  "required": ["user_id"]
}
```
Explain this schema.
"""
    shielded, mapping = guard.shield_text(raw_prompt)
    assert "\"properties\"" not in shielded
    assert len(mapping) == 1

    restored = guard.unshield_text(shielded, mapping)
    assert "\"properties\"" in restored
    assert "\"user_id\"" in restored
