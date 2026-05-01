# flake8: noqa: E501

from .base_prompts import CoderPrompts


class WholeFileFunctionPrompts(CoderPrompts):
    main_system = """Act as an expert software developer.
Take requests for changes to the supplied code.
If the request is ambiguous, ask questions.

Once you understand the request you MUST use the `write_file` function to edit the files to make the needed changes.
"""

    system_reminder = """
ONLY return code using the `write_file` function.
NEVER return code outside the `write_file` function.
"""

    files_content_prefix = "Here is the current content of the files:\n"
    files_no_full_files = "I am not sharing any files yet."

    redacted_edit_message = "No changes are needed."

    # repo_content_prefix is set to None for WholeFileFunctionPrompts
    # This is intentional as whole-file editing operates differently than
    # other editing modes. When using GPT-4 or other models, the file context
    # is provided directly in the edit operations, making repo summaries
    # less critical for this editing style.
    repo_content_prefix = None

    # Note: Chat history handling is simplified for whole-file editing
    # Full file history cannot be maintained in chat context due to token limits
    # When using whole-file editing mode, only the current file content is provided
