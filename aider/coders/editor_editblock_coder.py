"""
Editor Edit Block Coder Module

This module implements the Editor Edit Block Coder, which uses search/replace
blocks focused purely on editing files. This is a variant of the Edit Block Coder
optimized for editor workflows.

Key Features:
- Search/replace editing
- Editor-focused workflow
- Pure file editing
"""

from .editblock_coder import EditBlockCoder
from .editor_editblock_prompts import EditorEditBlockPrompts


class EditorEditBlockCoder(EditBlockCoder):
    "A coder that uses search/replace blocks, focused purely on editing files."
    edit_format = "editor-diff"
    gpt_prompts = EditorEditBlockPrompts()
