"""
Editor Whole File Coder Module

This module implements the Editor Whole File Coder, which operates on entire
files focused purely on editing files. This is a variant of the Whole File Coder
optimized for editor workflows.

Key Features:
- Entire file editing
- Editor-focused workflow
- Pure file editing
"""

from .editor_whole_prompts import EditorWholeFilePrompts
from .wholefile_coder import WholeFileCoder


class EditorWholeFileCoder(WholeFileCoder):
    "A coder that operates on entire files, focused purely on editing files."
    edit_format = "editor-whole"
    gpt_prompts = EditorWholeFilePrompts()
