"""
Edit Block Fenced Coder Module

This module implements the Edit Block Fenced Coder, which uses fenced
search/replace blocks for code modifications. This is a variant of the Edit Block
Coder that uses fenced code blocks for better delimitation.

Key Features:
- Fenced search/replace blocks
- Code block delimitation
- Enhanced edit format
"""

from ..dump import dump  # noqa: F401
from .editblock_coder import EditBlockCoder
from .editblock_fenced_prompts import EditBlockFencedPrompts


class EditBlockFencedCoder(EditBlockCoder):
    """A coder that uses fenced search/replace blocks for code modifications."""

    edit_format = "diff-fenced"
    gpt_prompts = EditBlockFencedPrompts()
