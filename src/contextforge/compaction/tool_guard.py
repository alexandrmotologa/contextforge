"""Tool-Call and Structured Output Guard for protecting schemas and function definitions."""

import re
import uuid
from typing import Dict, List, Tuple
from contextforge.core.models import ChatMessage

# Regex patterns for detecting structured tool definitions and XML/JSON blocks
TOOL_XML_REGEX = re.compile(
    r"(<(?:tools|tool_def|functions|function_call|tools_schema)>.*?</(?:tools|tool_def|functions|function_call|tools_schema)>)",
    re.DOTALL | re.IGNORECASE,
)
JSON_SCHEMA_BLOCK_REGEX = re.compile(
    r"(```(?:json)?\s*\{[\s\S]*?\"(?:type|properties|parameters|required|functions)\"[\s\S]*?\}\s*```)",
    re.DOTALL,
)
OPENAPI_SCHEMA_REGEX = re.compile(
    r"(\{\s*\"(?:name|type|description|parameters)\"\s*:\s*\"?[a-zA-Z0-9_\-\.]+\"?[\s\S]*?\"parameters\"\s*:\s*\{[\s\S]*?\}\s*\})",
    re.DOTALL,
)


class ToolGuard:
    """Shields function calling schemas and tool messages from lossy compaction."""

    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    def is_protected_message(self, message: ChatMessage) -> bool:
        """Return True if message role or content represents immutable tool interaction."""
        if not self.enabled:
            return False

        # Direct tool roles or messages with tool calls
        if message.role in ("tool", "function"):
            return True
        if message.tool_calls is not None and len(message.tool_calls) > 0:
            return True
        if message.tool_call_id is not None:
            return True

        return False

    def shield_text(self, text: str) -> Tuple[str, Dict[str, str]]:
        """Replace tool definitions and schemas with opaque placeholders.

        Returns:
            (shielded_text, placeholder_map)
        """
        if not self.enabled or not text:
            return text, {}

        placeholder_map: Dict[str, str] = {}
        shielded = text

        # Helper replacer
        def replace_with_guard(match: re.Match) -> str:
            full_match = match.group(0)
            token_id = f"__CF_TOOL_GUARD_{uuid.uuid4().hex[:8]}__"
            placeholder_map[token_id] = full_match
            return token_id

        # Pass 1: Tool XML blocks (<tools>...</tools>)
        shielded = TOOL_XML_REGEX.sub(replace_with_guard, shielded)

        # Pass 2: JSON Schema blocks within markdown fences
        shielded = JSON_SCHEMA_BLOCK_REGEX.sub(replace_with_guard, shielded)

        return shielded, placeholder_map

    def unshield_text(self, shielded_text: str, placeholder_map: Dict[str, str]) -> str:
        """Restore protected tool definitions back to their exact original text."""
        if not placeholder_map or not shielded_text:
            return shielded_text

        restored = shielded_text
        for token_id, original_content in placeholder_map.items():
            restored = restored.replace(token_id, original_content)

        return restored
