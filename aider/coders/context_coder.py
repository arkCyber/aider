"""
Context Coder Module

This module implements the Context Coder, which identifies which files need to be
edited for a given request. It uses repository mapping to understand the codebase
structure and identify relevant files.

Key Features:
- File identification for editing
- Repository context understanding
- Map-based file selection
"""

from .base_coder import Coder
from .context_prompts import ContextPrompts


class ContextCoder(Coder):
    """Identify which files need to be edited for a given request."""

    edit_format = "context"
    gpt_prompts = ContextPrompts()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if not self.repo_map:
            return

        self.repo_map.refresh = "always"
        self.repo_map.max_map_tokens *= self.repo_map.map_mul_no_files
        self.repo_map.map_mul_no_files = 1.0

    def reply_completed(self):
        """
        Called when the AI has completed identifying files to edit.
        
        This method displays the phase results showing which files
        were identified for editing.
        """
        content = self.partial_response_content
        if not content or not content.strip():
            return True

        # Show phase results summary with specific details
        if self.io.pretty:
            current_rel_fnames = set(self.get_inchat_relative_files())
            mentioned_rel_fnames = set(self.get_file_mentions(content, ignore_current=True))
            
            # Calculate specific statistics
            added_files = mentioned_rel_fnames - current_rel_fnames
            removed_files = current_rel_fnames - mentioned_rel_fnames
            content_lines = len(content.splitlines())
            
            self.io.tool_output("\n" + "─" * 60, log_only=False)
            self.io.tool_output("📊 Phase Results Summary", log_only=False, bold=True)
            self.io.tool_output("─" * 60, log_only=False)
            self.io.tool_output("✅ File identification phase completed", log_only=False)
            self.io.tool_output(f"   • Files currently in chat: {len(current_rel_fnames)}", log_only=False)
            self.io.tool_output(f"   • Files identified for editing: {len(mentioned_rel_fnames)}", log_only=False)
            if added_files:
                self.io.tool_output(f"   • Files to be added: {len(added_files)}", log_only=False)
                for fname in sorted(added_files):
                    self.io.tool_output(f"     - {fname}", log_only=False)
            if removed_files:
                self.io.tool_output(f"   • Files to be removed: {len(removed_files)}", log_only=False)
                for fname in sorted(removed_files):
                    self.io.tool_output(f"     - {fname}", log_only=False)
            self.io.tool_output(f"   • Analysis content: {content_lines} lines", log_only=False)
            self.io.tool_output("─" * 60, log_only=False)
            self.io.tool_output("", log_only=False)

        # dump(repr(content))
        current_rel_fnames = set(self.get_inchat_relative_files())
        mentioned_rel_fnames = set(self.get_file_mentions(content, ignore_current=True))

        # dump(current_rel_fnames)
        # dump(mentioned_rel_fnames)
        # dump(current_rel_fnames == mentioned_rel_fnames)

        if mentioned_rel_fnames == current_rel_fnames:
            return True

        if self.num_reflections >= self.max_reflections - 1:
            return True

        self.abs_fnames = set()
        for fname in mentioned_rel_fnames:
            self.add_rel_fname(fname)
        # dump(self.get_inchat_relative_files())

        self.reflected_message = self.gpt_prompts.try_again

        # mentioned_idents = self.get_ident_mentions(cur_msg_text)
        # if mentioned_idents:

        return True

    def check_for_file_mentions(self, content):
        """
        Check if file mentions are present in the content.
        
        Args:
            content: Content to check for file mentions
            
        Returns:
            List of mentioned files or empty list if none found
        """
        if not content or not content.strip():
            return []
        
        # Get file mentions from the content
        mentioned_files = self.get_file_mentions(content, ignore_current=True)
        
        return mentioned_files
