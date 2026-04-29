"""
Editor Diff Fenced Coder Module

This module implements the Editor Diff Fenced Coder, which uses fenced
search/replace blocks focused purely on editing files. This is a variant of the
Edit Block Fenced Coder optimized for editor workflows.

Key Features:
- Fenced search/replace editing
- Editor-focused workflow
- Pure file editing
"""

from .editblock_fenced_coder import EditBlockFencedCoder
from .editor_diff_fenced_prompts import EditorDiffFencedPrompts


class EditorDiffFencedCoder(EditBlockFencedCoder):
    "A coder that uses search/replace blocks, focused purely on editing files."

    edit_format = "editor-diff-fenced"
    gpt_prompts = EditorDiffFencedPrompts()
