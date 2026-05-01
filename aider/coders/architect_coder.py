"""
Architect Coder Module

This module implements the Architect Coder, which provides a two-phase workflow
for code generation:
1. Planning phase: Analyze the codebase and generate a plan
2. Execution phase: Apply the plan to edit files

The Architect Coder separates planning from execution, allowing users to review
the plan before making changes to the codebase.
"""

from .architect_prompts import ArchitectPrompts
from .ask_coder import AskCoder
from .base_coder import Coder


class ArchitectCoder(AskCoder):
    edit_format = "architect"
    gpt_prompts = ArchitectPrompts()
    auto_accept_architect = False

    def reply_completed(self):
        content = self.partial_response_content

        if not content or not content.strip():
            return

        # Show visual indicator that this is the planning phase
        if self.io.pretty:
            self.io.tool_output("\n" + "─" * 60, log_only=False)
            self.io.tool_output("📋 Planning phase complete", log_only=False, bold=True)
            self.io.tool_output("─" * 60, log_only=False)
            self.io.tool_info("Review the plan above before proceeding", log_only=False)
            self.io.tool_output("", log_only=False)

        # Show work results summary
        if self.io.pretty:
            self.io.tool_output("─" * 60, log_only=False)
            self.io.tool_output("📊 Phase Results Summary", log_only=False, bold=True)
            self.io.tool_output("─" * 60, log_only=False)
            self.io.tool_output("✅ Planning phase completed successfully", log_only=False)
            self.io.tool_output("   • Plan generated and ready for review", log_only=False)
            self.io.tool_output("   • No files modified yet", log_only=False)
            self.io.tool_output("   • Awaiting user confirmation to proceed", log_only=False)
            self.io.tool_output("─" * 60, log_only=False)
            self.io.tool_output("", log_only=False)

        if not self.auto_accept_architect and not self.io.confirm_ask("Proceed with the planned changes?"):
            self.io.tool_output("─" * 60, log_only=False)
            self.io.tool_warning("Plan cancelled. No files were modified.", log_only=False)
            self.io.tool_output("─" * 60, log_only=False)
            return

        kwargs = dict()

        # Use the editor_model from the main_model if it exists, otherwise use the main_model itself
        editor_model = self.main_model.editor_model or self.main_model

        kwargs["main_model"] = editor_model
        kwargs["edit_format"] = self.main_model.editor_edit_format
        kwargs["suggest_shell_commands"] = False
        kwargs["map_tokens"] = 0
        kwargs["total_cost"] = self.total_cost
        kwargs["cache_prompts"] = False
        kwargs["num_cache_warming_pings"] = 0
        kwargs["summarize_from_coder"] = False

        new_kwargs = dict(io=self.io, from_coder=self)
        new_kwargs.update(kwargs)

        editor_coder = Coder.create(**new_kwargs)
        editor_coder.cur_messages = []
        editor_coder.done_messages = []

        if self.verbose:
            editor_coder.show_announcements()

        editor_coder.run(with_message=content, preproc=False)

        self.move_back_cur_messages("I made those changes to the files.")
        self.total_cost = editor_coder.total_cost
        self.aider_commit_hashes = editor_coder.aider_commit_hashes
