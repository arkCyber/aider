"""
Ask Coder Module

This module implements the Ask Coder, which allows users to ask questions
about code without making any changes. This is useful for code review,
understanding, and exploration.

Key Features:
- Question answering
- Code analysis without modification
- Code exploration
"""

from .ask_prompts import AskPrompts
from .base_coder import Coder


class AskCoder(Coder):
    """Ask questions about code without making any changes."""

    edit_format = "ask"
    gpt_prompts = AskPrompts()
