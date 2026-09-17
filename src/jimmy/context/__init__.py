# src/jimmy/context/__init__.py
"""🧠 Jimmy's token-efficient context building."""

from .builder import SYSTEM_PROMPT, TOOL_STUB, ContextBuilder

__all__ = ["SYSTEM_PROMPT", "TOOL_STUB", "ContextBuilder"]
