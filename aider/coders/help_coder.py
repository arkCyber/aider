"""
Help Coder Module

This module implements the Help Coder, which provides interactive help and
documentation about aider. It allows users to ask questions about how to use
the Aider AI coding assistant.

Key Features:
- Interactive help system
- Documentation display
- Usage guidance
"""

from ..dump import dump  # noqa: F401
from .base_coder import Coder
from .help_prompts import HelpPrompts


class HelpCoder(Coder):
    """Interactive help and documentation about aider."""

    edit_format = "help"
    gpt_prompts = HelpPrompts()

    def get_edits(self, mode="update"):
        return []

    def apply_edits(self, edits):
        """
        Apply edits to files.
        
        Args:
            edits: List of edits to apply
            
        Note:
            HelpCoder does not apply edits as it only provides
            interactive help and documentation. This method
            is a no-op for the HelpCoder.
        """
        # HelpCoder is read-only and does not apply file edits
        # It only displays help information and documentation
        pass
