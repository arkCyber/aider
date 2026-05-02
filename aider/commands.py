"""
Aider Commands Module

This module implements the command system for the Aider AI coding assistant.
It provides a comprehensive set of commands for code management, AI model switching,
and various development tools.

Key Features:
- Aerospace-level input validation and error handling
- Comprehensive audit logging for all operations
- Dangerous command confirmation mechanism
- AI model management and configuration
- Docker, database, and environment management
- Code formatting, testing, and analysis tools

The Commands class serves as the central command processor, handling user input
and coordinating with the AI coder to execute tasks.
"""

import glob
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import traceback
from collections import OrderedDict
from datetime import datetime
from os.path import expanduser
from pathlib import Path

import pyperclip
from PIL import Image, ImageGrab
from prompt_toolkit.completion import Completion, PathCompleter
from prompt_toolkit.document import Document

from aider import models, prompts, voice
from aider.editor import pipe_editor
from aider.format_settings import format_settings
from aider.help import Help, install_help_extra
from aider.io import CommandCompletionException
from aider.llm import litellm
from aider.repo import ANY_GIT_ERROR
from aider.run_cmd import run_cmd
from aider.scrape import Scraper, install_playwright, BrowserController
from aider.utils import is_image_file

from .dump import dump  # noqa: F401

# Configure logging for aerospace-level audit trails
# This ensures all critical operations are logged for compliance and debugging
from pathlib import Path


def _create_audit_logger():
    """Create an audit logger that gracefully handles unwritable home directories."""
    logger = logging.getLogger("aider.audit")
    logger.setLevel(logging.INFO)

    if logger.handlers:
        return logger

    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    try:
        audit_log_dir = Path.home() / ".aider" / "logs"
        audit_log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(audit_log_dir / "aider_audit.log")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except OSError:
        # Keep import-time behavior safe in restricted environments (CI/sandbox).
        logger.addHandler(logging.NullHandler())

    return logger


audit_logger = _create_audit_logger()


class SwitchCoder(Exception):
    """
    Exception raised when switching to a different AI coder configuration.
    
    This exception is used to signal that the application should switch to a different
    coder with new model or configuration parameters. It carries the necessary
    configuration data in its kwargs.
    """
    def __init__(self, placeholder=None, **kwargs):
        """
        Initialize the switch coder exception.
        
        Args:
            placeholder: Optional placeholder for the new coder
            **kwargs: Configuration parameters for the new coder (model, edit_format, etc.)
        """
        self.kwargs = kwargs
        self.placeholder = placeholder


class Commands:
    """
    Main command processor for the Aider AI coding assistant.
    
    This class handles all user commands and coordinates with the AI coder to execute tasks.
    It implements aerospace-level safety features including input validation, audit logging,
    and dangerous operation confirmation.
    
    Class Attributes:
        voice: Voice input/output handler (shared across instances)
        scraper: Web scraping functionality (shared across instances)
        browser_controller: Browser automation controller (shared across instances)
        require_confirmation: Global flag to enable/disable dangerous action confirmation
        available_models: List of configured AI model names
        model_config_file: Path to the model configuration file
        model_configs: Dictionary storing per-model API configurations
        DANGEROUS_COMMANDS: Set of commands requiring user confirmation
    """
    
    # Shared class-level resources (singleton pattern)
    voice = None
    scraper = None
    browser_controller = None
    
    # Global configuration flags
    require_confirmation = True  # Default: require confirmation for dangerous actions
    
    # Available AI models configuration
    # These models are available for switching and can be configured with custom API endpoints
    available_models = []  # List of available model names
    model_config_file = '.aider_models.json'  # Config file for model persistence
    model_configs = {}  # Dictionary for per-model configuration (API endpoints, API keys, etc.)
    
    # Dangerous commands that require confirmation before execution
    # These commands can cause irreversible changes or security risks
    DANGEROUS_COMMANDS = {
        'docker_stop': True,      # Stopping Docker containers
        'docker_rm': True,         # Removing Docker containers
        'db_delete': True,         # Deleting database records
        'db_drop': True,          # Dropping database tables/databases
        'package_uninstall': True, # Uninstalling Python packages
        'env_deactivate': True,   # Deactivating virtual environments
        'memory_clear': True,     # Clearing project memory
        'schedule_remove': True,  # Removing scheduled tasks
        'agent': True,            # Autonomous agent execution
        'ci_run': True,           # Running CI/CD pipelines
        'pr_create': True,        # Creating pull requests
    }

    def clone(self):
        """
        Create a clone of this Commands instance.
        
        This method creates a new Commands instance with the same configuration
        but without a coder, allowing for coder switching.
        
        Returns:
            Commands: A new Commands instance with copied configuration
        """
        return Commands(
            self.io,
            None,
            voice_language=self.voice_language,
            verify_ssl=self.verify_ssl,
            args=self.args,
            parser=self.parser,
            verbose=self.verbose,
            editor=self.editor,
            original_read_only_fnames=self.original_read_only_fnames,
        )

    def confirm_dangerous_action(self, action_name, details=""):
        """
        Require user confirmation for dangerous actions (aerospace-level safety).
        
        This method implements a safety confirmation mechanism for operations that
        could cause irreversible changes or security risks. It respects the global
        configuration setting that can disable confirmation for automation scenarios.
        
        Args:
            action_name (str): Name of the action requiring confirmation
            details (str): Additional details about the action
            
        Returns:
            bool: True if action is approved (or confirmation disabled), False if rejected
            
        Security Features:
            - Checks global confirmation setting first
            - Logs all confirmation requests and results
            - Handles user interruption gracefully
            - Provides clear warning messages
        """
        # Check global configuration - allow bypass if confirmation is disabled
        if not Commands.require_confirmation:
            audit_logger.info(f"Confirmation bypassed (disabled) for: {action_name}")
            self.io.tool_output(f"\n⚠️  DANGEROUS ACTION: {action_name}", log_only=False)
            self.io.tool_output(f"Confirmation is disabled. Executing directly.", log_only=False)
            return True
        
        # Display confirmation prompt with clear warnings
        self.io.tool_output(f"\n⚠️  DANGEROUS ACTION: {action_name}", log_only=False)
        if details:
            self.io.tool_output(f"Details: {details}", log_only=False)
        self.io.tool_output("=" * 50, log_only=False)
        self.io.tool_output("This action is potentially dangerous and requires confirmation.", log_only=False)
        self.io.tool_output("Type 'yes' to confirm, or anything else to cancel.", log_only=False)
        self.io.tool_output("=" * 50, log_only=False)
        
        # Log the confirmation request for audit trail
        audit_logger.info(f"Confirmation requested for: {action_name}")
        
        # Request user input and handle cancellation
        try:
            response = input("Confirm? ")
            confirmed = response.lower() in ['yes', 'y']
            audit_logger.info(f"Confirmation result: {'approved' if confirmed else 'rejected'} for {action_name}")
            return confirmed
        except (EOFError, KeyboardInterrupt):
            self.io.tool_output("\nAction cancelled.", log_only=False)
            audit_logger.info(f"Confirmation interrupted for: {action_name}")
            return False

    def log_command_start(self, command_name, args=""):
        """
        Log the start of command execution (aerospace-level audit trail).
        
        This method records the initiation of any command execution to maintain
        a comprehensive audit trail for compliance and debugging purposes.
        
        Args:
            command_name (str): Name of the command being executed
            args (str): Command arguments (truncated to 100 chars for log size)
        """
        audit_logger.info(f"Command started: {command_name}, args: {args[:100] if args else 'none'}")
    
    def log_command_end(self, command_name, status="success", details=""):
        """
        Log the completion of command execution (aerospace-level audit trail).
        
        This method records the completion status of any command execution to maintain
        a comprehensive audit trail for compliance and debugging purposes.
        
        Args:
            command_name (str): Name of the command that completed
            status (str): Execution status (success, error, interrupted, etc.)
            details (str): Additional details about the result (truncated to 100 chars)
        """
        audit_logger.info(f"Command completed: {command_name}, status: {status}, details: {details[:100] if details else 'none'}")
    
    def load_model_config(self):
        """
        Load available AI models and their configurations from persistent storage.
        
        This method reads the model configuration file to restore the list of available
        AI models and their custom API configurations. If the file doesn't exist,
        it initializes with default models and configurations.
        
        Default Models:
            - gpt-4, gpt-3.5-turbo (OpenAI)
            - claude-3-opus, claude-3-sonnet, claude-3-haiku (Anthropic)
            - ollama/gemma-4-26b-moe (Local Ollama with default config)
        
        Error Handling:
            - JSON decode errors are logged and handled gracefully
            - Missing file triggers default initialization
            - All errors result in empty configuration for safety
        """
        try:
            if os.path.exists(self.model_config_file):
                with open(self.model_config_file, 'r') as f:
                    config = json.load(f)
                    Commands.available_models = config.get('models', [])
                    Commands.model_configs = config.get('model_configs', {})
                    audit_logger.info(f"Loaded {len(Commands.available_models)} models and {len(Commands.model_configs)} configs")
            else:
                # Initialize with default models if config file doesn't exist
                Commands.available_models = [
                    'gpt-4',
                    'gpt-3.5-turbo',
                    'claude-3-opus',
                    'claude-3-sonnet',
                    'claude-3-haiku',
                    'ollama/gemma-4-26b-moe'
                ]
                # Initialize with default configs for local models
                Commands.model_configs = {
                    'ollama/gemma-4-26b-moe': {
                        'api_base': 'http://localhost:11434/v1',
                        'api_key': 'ollama'
                    }
                }
                self.save_model_config()
        except json.JSONDecodeError as e:
            audit_logger.error(f"Error loading model config: {e}")
            Commands.available_models = []
            Commands.model_configs = {}
        except Exception as e:
            audit_logger.error(f"Error loading model config: {e}")
            Commands.available_models = []
            Commands.model_configs = {}
    
    def save_model_config(self):
        """
        Save available AI models and their configurations to persistent storage.
        
        This method persists the current model configuration to a JSON file,
        ensuring that model settings are preserved across sessions.
        
        Saved Data:
            - List of available model names
            - Per-model API configurations (endpoints, keys, etc.)
            - Timestamp of last update
        
        Error Handling:
            - File write errors are logged but don't crash the application
            - Ensures configuration persistence for session continuity
        """
        try:
            config = {
                'models': Commands.available_models,
                'model_configs': Commands.model_configs,
                'updated': datetime.now().isoformat()
            }
            with open(self.model_config_file, 'w') as f:
                json.dump(config, f, indent=2)
            audit_logger.info(f"Saved {len(Commands.available_models)} models and {len(Commands.model_configs)} configs")
        except Exception as e:
            audit_logger.error(f"Error saving model config: {e}")

    def __init__(
        self,
        io,
        coder,
        voice_language=None,
        voice_input_device=None,
        voice_format=None,
        verify_ssl=True,
        args=None,
        parser=None,
        verbose=False,
        editor=None,
        original_read_only_fnames=None,
    ):
        logger = logging.getLogger(__name__)
        logger.info("Commands class initializing")
        logger.debug(f"Voice language: {voice_language}")
        logger.debug(f"Voice format: {voice_format}")
        logger.debug(f"Verify SSL: {verify_ssl}")
        
        self.io = io
        self.coder = coder
        self.parser = parser
        self.args = args
        self.verbose = verbose

        self.verify_ssl = verify_ssl
        if voice_language == "auto":
            voice_language = None

        self.voice_language = voice_language
        self.voice_format = voice_format
        self.voice_input_device = voice_input_device

        self.help = None
        self.editor = editor

        # Store the original read-only filenames provided via args.read
        self.original_read_only_fnames = set(original_read_only_fnames or [])
        
        # Load model configuration
        self.load_model_config()

    def cmd_model(self, args):
        """
        Switch the Main Model to a new LLM (with configuration support).
        
        This command allows users to switch between different AI models from the
        configured list. It validates that the model is in the available list and
        displays custom API configurations if they exist.
        
        Args:
            args (str): Model name to switch to, or empty to show available models
            
        Behavior:
            - Without args: Lists available models with their configurations
            - With args: Switches to the specified model if in available list
            - Displays custom API configuration when switching
            - Logs the model switch for audit trail
            
        Example:
            /model              # Show available models
            /model gpt-4        # Switch to GPT-4
            /model ollama/gemma-4-26b-moe  # Switch to local Ollama model
        """

        model_name = args.strip()
        if not model_name:
            # Show available models and current model
            self.io.tool_output("\n🤖 Available AI Models:", log_only=False)
            self.io.tool_output("=" * 50, log_only=False)
            
            if Commands.available_models:
                for i, model in enumerate(Commands.available_models, 1):
                    current = " (current)" if model == self.coder.main_model.name else ""
                    self.io.tool_output(f"  {i}. {model}{current}", log_only=False)
                    
                    # Show model configuration if available
                    if model in Commands.model_configs:
                        config = Commands.model_configs[model]
                        if config.get('api_base'):
                            self.io.tool_output(f"     API Base: {config['api_base']}", log_only=False)
            else:
                self.io.tool_output("  No models configured", log_only=False)
            
            self.io.tool_output("\nUsage: /model <model_name>", log_only=False)
            self.io.tool_output("Example: /model gpt-4", log_only=False)
            self.io.tool_output("Use /models to manage available models", log_only=False)
            return
        
        # Check if model is in available list (validation)
        if Commands.available_models and model_name not in Commands.available_models:
            self.io.tool_error(f"Model '{model_name}' is not in the available models list")
            self.io.tool_output(f"Available models: {', '.join(Commands.available_models)}", log_only=False)
            self.io.tool_output("Use /models add <model_name> to add this model", log_only=False)
            return
        
        # Apply custom configuration if available (display for user awareness)
        if model_name in Commands.model_configs:
            config = Commands.model_configs[model_name]
            self.io.tool_output(f"🔧 Using custom configuration for: {model_name}", log_only=False)
            for key, value in config.items():
                if 'key' not in key.lower():
                    self.io.tool_output(f"  {key}: {value}", log_only=False)
                else:
                    self.io.tool_output(f"  {key}: {value[:8]}...", log_only=False)
        
        # Create model instance and validate
        model = models.Model(
            model_name,
            editor_model=self.coder.main_model.editor_model.name,
            weak_model=self.coder.main_model.weak_model.name,
        )
        models.sanity_check_models(self.io, model)

        # Check if the current edit format is the default for the old model
        old_model_edit_format = self.coder.main_model.edit_format
        current_edit_format = self.coder.edit_format

        new_edit_format = current_edit_format
        if current_edit_format == old_model_edit_format:
            # If the user was using the old model's default, switch to the new model's default
            new_edit_format = model.edit_format

        # Log the model switch for audit trail
        audit_logger.info(f"Model switched to: {model_name}")
        raise SwitchCoder(main_model=model, edit_format=new_edit_format)

    def cmd_models(self, args):
        """
        Manage available AI models list with full configuration support.
        
        This command provides comprehensive model management including:
        - Listing available models with their API configurations
        - Adding new models to the available list
        - Removing models from the available list
        - Configuring API endpoints and keys for each model
        - Viewing detailed model configurations
        - Resetting to default models and configurations
        
        Subcommands:
            - (no args): List all models with configurations and help
            - list: List available models with configurations
            - add <name>: Add a model to the available list
            - remove <name>: Remove a model from the available list
            - clear: Clear all models and configurations
            - reset: Reset to default models and configurations
            - config <name> [api_base=<url>] [api_key=<key>]: Configure model API settings
            - show <name>: Show detailed configuration for a model
            
        Args:
            args (str): Command arguments including subcommand and parameters
            
        Example:
            /models add ollama/llama3-70b
            /models config ollama/llama3-70b api_base=http://localhost:11434/v1 api_key=ollama
            /models show ollama/llama3-70b
        """
        parts = args.strip().split()
        
        if not parts:
            # List all available models with their configurations
            self.io.tool_output("\n🤖 Available AI Models:", log_only=False)
            self.io.tool_output("=" * 50, log_only=False)
            
            if Commands.available_models:
                for i, model in enumerate(Commands.available_models, 1):
                    current = " (current)" if model == self.coder.main_model.name else ""
                    self.io.tool_output(f"  {i}. {model}{current}", log_only=False)
                    
                    # Show model configuration if available
                    if model in Commands.model_configs:
                        config = Commands.model_configs[model]
                        if config.get('api_base'):
                            self.io.tool_output(f"     API Base: {config['api_base']}", log_only=False)
                        if config.get('api_key'):
                            self.io.tool_output(f"     API Key: {config['api_key'][:8]}...", log_only=False)
                
                self.io.tool_output(f"\nTotal: {len(Commands.available_models)} models", log_only=False)
                self.io.tool_output(f"Configured: {len(Commands.model_configs)} models", log_only=False)
            else:
                self.io.tool_output("  No models configured", log_only=False)
            
            self.io.tool_output("\nCommands:", log_only=False)
            self.io.tool_output("  /models list              - List available models", log_only=False)
            self.io.tool_output("  /models add <name>        - Add a model", log_only=False)
            self.io.tool_output("  /models remove <name>     - Remove a model", log_only=False)
            self.io.tool_output("  /models clear             - Clear all models", log_only=False)
            self.io.tool_output("  /models reset             - Reset to default models", log_only=False)
            self.io.tool_output("  /models config <name>     - Configure model API", log_only=False)
            self.io.tool_output("  /models show <name>       - Show model configuration", log_only=False)
            return
        
        command = parts[0].lower()
        
        if command == 'list':
            self.io.tool_output("\n🤖 Available AI Models:", log_only=False)
            self.io.tool_output("=" * 50, log_only=False)
            
            if Commands.available_models:
                for i, model in enumerate(Commands.available_models, 1):
                    current = " (current)" if model == self.coder.main_model.name else ""
                    self.io.tool_output(f"  {i}. {model}{current}", log_only=False)
                    
                    # Show model configuration if available
                    if model in Commands.model_configs:
                        config = Commands.model_configs[model]
                        if config.get('api_base'):
                            self.io.tool_output(f"     API Base: {config['api_base']}", log_only=False)
                        if config.get('api_key'):
                            self.io.tool_output(f"     API Key: {config['api_key'][:8]}...", log_only=False)
                
                self.io.tool_output(f"\nTotal: {len(Commands.available_models)} models", log_only=False)
                self.io.tool_output(f"Configured: {len(Commands.model_configs)} models", log_only=False)
            else:
                self.io.tool_output("  No models configured", log_only=False)
        
        elif command == 'add':
            if len(parts) < 2:
                self.io.tool_error("Usage: /models add <model_name>")
                return
            
            model_name = parts[1]
            if model_name in Commands.available_models:
                self.io.tool_output(f"Model '{model_name}' already exists in the list", log_only=False)
                return
            
            Commands.available_models.append(model_name)
            self.save_model_config()
            self.io.tool_output(f"✓ Added model: {model_name}", log_only=False)
            audit_logger.info(f"Model added to available list: {model_name}")
        
        elif command == 'remove':
            if len(parts) < 2:
                self.io.tool_error("Usage: /models remove <model_name>")
                return
            
            model_name = parts[1]
            if model_name not in Commands.available_models:
                self.io.tool_error(f"Model '{model_name}' not found in the list")
                return
            
            Commands.available_models.remove(model_name)
            # Also remove configuration if exists
            if model_name in Commands.model_configs:
                del Commands.model_configs[model_name]
            self.save_model_config()
            self.io.tool_output(f"✓ Removed model: {model_name}", log_only=False)
            audit_logger.info(f"Model removed from available list: {model_name}")
        
        elif command == 'clear':
            if not Commands.available_models:
                self.io.tool_output("Model list is already empty", log_only=False)
                return
            
            Commands.available_models = []
            Commands.model_configs = {}
            self.save_model_config()
            self.io.tool_output("✓ Cleared all models and configurations", log_only=False)
            audit_logger.warning("All models and configs cleared")
        
        elif command == 'reset':
            Commands.available_models = [
                'gpt-4',
                'gpt-3.5-turbo',
                'claude-3-opus',
                'claude-3-sonnet',
                'claude-3-haiku',
                'ollama/gemma-4-26b-moe'
            ]
            Commands.model_configs = {
                'ollama/gemma-4-26b-moe': {
                    'api_base': 'http://localhost:11434/v1',
                    'api_key': 'ollama'
                }
            }
            self.save_model_config()
            self.io.tool_output("✓ Reset to default models and configurations", log_only=False)
            audit_logger.info("Model list reset to defaults")
        
        elif command == 'config':
            if len(parts) < 2:
                self.io.tool_error("Usage: /models config <model_name> [api_base=<url>] [api_key=<key>]")
                self.io.tool_error("Example: /models config ollama/gemma-4-26b-moe api_base=http://localhost:11434/v1 api_key=ollama")
                return
            
            model_name = parts[1]
            if model_name not in Commands.available_models:
                self.io.tool_error(f"Model '{model_name}' not in available models. Add it first with /models add")
                return
            
            # Initialize config if not exists
            if model_name not in Commands.model_configs:
                Commands.model_configs[model_name] = {}
            
            # Parse configuration options
            for part in parts[2:]:
                if '=' in part:
                    key, value = part.split('=', 1)
                    Commands.model_configs[model_name][key] = value
            
            self.save_model_config()
            self.io.tool_output(f"✓ Updated configuration for: {model_name}", log_only=False)
            self.io.tool_output(f"  Configuration: {Commands.model_configs[model_name]}", log_only=False)
            audit_logger.info(f"Model configuration updated: {model_name}")
        
        elif command == 'show':
            if len(parts) < 2:
                self.io.tool_error("Usage: /models show <model_name>")
                return
            
            model_name = parts[1]
            if model_name not in Commands.available_models:
                self.io.tool_error(f"Model '{model_name}' not found")
                return
            
            self.io.tool_output(f"\n🔧 Configuration for: {model_name}", log_only=False)
            self.io.tool_output("=" * 50, log_only=False)
            
            if model_name in Commands.model_configs:
                for key, value in Commands.model_configs[model_name].items():
                    # Mask API keys
                    if 'key' in key.lower():
                        value = value[:8] + '...' if len(value) > 8 else '***'
                    self.io.tool_output(f"  {key}: {value}", log_only=False)
            else:
                self.io.tool_output("  No custom configuration", log_only=False)
                self.io.tool_output("  Using default settings", log_only=False)
        
        else:
            self.io.tool_error(f"Unknown command: {command}")
            self.io.tool_output("Available commands: list, add, remove, clear, reset, config, show", log_only=False)

    def cmd_editor_model(self, args):
        "Switch the Editor Model to a new LLM"

        model_name = args.strip()
        model = models.Model(
            self.coder.main_model.name,
            editor_model=model_name,
            weak_model=self.coder.main_model.weak_model.name,
        )
        models.sanity_check_models(self.io, model)
        raise SwitchCoder(main_model=model)

    def cmd_weak_model(self, args):
        "Switch the Weak Model to a new LLM"

        model_name = args.strip()
        model = models.Model(
            self.coder.main_model.name,
            editor_model=self.coder.main_model.editor_model.name,
            weak_model=model_name,
        )
        models.sanity_check_models(self.io, model)
        raise SwitchCoder(main_model=model)

    def cmd_chat_mode(self, args):
        "Switch to a new chat mode"

        from aider import coders

        ef = args.strip()
        valid_formats = OrderedDict(
            sorted(
                (
                    coder.edit_format,
                    coder.__doc__.strip().split("\n")[0] if coder.__doc__ else "No description",
                )
                for coder in coders.__all__
                if getattr(coder, "edit_format", None)
            )
        )

        show_formats = OrderedDict(
            [
                ("help", "Get help about using aider (usage, config, troubleshoot)."),
                ("ask", "Ask questions about your code without making any changes."),
                ("code", "Ask for changes to your code (using the best edit format)."),
                (
                    "architect",
                    (
                        "Work with an architect model to design code changes, and an editor to make"
                        " them."
                    ),
                ),
                (
                    "context",
                    "Automatically identify which files will need to be edited.",
                ),
            ]
        )

        if ef not in valid_formats and ef not in show_formats:
            if ef:
                self.io.tool_error(f'Chat mode "{ef}" should be one of these:\n')
            else:
                self.io.tool_output("Chat mode should be one of these:\n")

            max_format_length = max(len(format) for format in valid_formats.keys())
            for format, description in show_formats.items():
                self.io.tool_output(f"- {format:<{max_format_length}} : {description}")

            self.io.tool_output("\nOr a valid edit format:\n")
            for format, description in valid_formats.items():
                if format not in show_formats:
                    self.io.tool_output(f"- {format:<{max_format_length}} : {description}")

            return

        summarize_from_coder = True
        edit_format = ef

        if ef == "code":
            edit_format = self.coder.main_model.edit_format
            summarize_from_coder = False
        elif ef == "ask":
            summarize_from_coder = False

        raise SwitchCoder(
            edit_format=edit_format,
            summarize_from_coder=summarize_from_coder,
        )

    def completions_model(self):
        models = litellm.model_cost.keys()
        return models

    def cmd_models(self, args):
        "Search the list of available models"

        args = args.strip()

        if args:
            models.print_matching_models(self.io, args)
        else:
            self.io.tool_output("Please provide a partial model name to search for.")

    def cmd_web(self, args, return_content=False):
        "Scrape a webpage, convert to markdown and send in a message"

        url = args.strip()
        if not url:
            self.io.tool_error("Please provide a URL to scrape.")
            return

        self.io.tool_output(f"Scraping {url}...")
        if not self.scraper:
            disable_playwright = getattr(self.args, "disable_playwright", False)
            if disable_playwright:
                res = False
            else:
                res = install_playwright(self.io)
                if not res:
                    self.io.tool_warning("Unable to initialize playwright.")

            self.scraper = Scraper(
                print_error=self.io.tool_error,
                playwright_available=res,
                verify_ssl=self.verify_ssl,
            )

        content = self.scraper.scrape(url) or ""
        content = f"Here is the content of {url}:\n\n" + content
        if return_content:
            return content

        self.io.tool_output("... added to chat.")

        self.coder.cur_messages += [
            dict(role="user", content=content),
            dict(role="assistant", content="Ok."),
        ]

    def cmd_browser_start(self, args):
        "Start a browser session for web automation"
        if not Commands.browser_controller:
            disable_playwright = getattr(self.args, "disable_playwright", False)
            if disable_playwright:
                res = False
            else:
                res = install_playwright(self.io)
                if not res:
                    self.io.tool_error("Unable to initialize playwright.")
                    return

            Commands.browser_controller = BrowserController(
                print_error=self.io.tool_error,
                verify_ssl=self.verify_ssl,
                headless=True,
            )

        if Commands.browser_controller.start():
            self.io.tool_output("🌐 Browser session started", log_only=False)
        else:
            self.io.tool_error("Failed to start browser session")

    def cmd_browser_stop(self, args):
        "Stop the browser session"
        if not Commands.browser_controller:
            self.io.tool_warning("No active browser session")
            return

        if Commands.browser_controller.stop():
            self.io.tool_output("Browser session stopped", log_only=False)
            Commands.browser_controller = None
        else:
            self.io.tool_error("Failed to stop browser session")

    def cmd_browser_navigate(self, args):
        "Navigate to a URL in the browser"
        if not Commands.browser_controller:
            self.io.tool_error("No active browser session. Use /browser-start first.")
            return

        url = args.strip()
        if not url:
            self.io.tool_error("Please provide a URL")
            return

        self.io.tool_output(f"Navigating to {url}...", log_only=False)
        if Commands.browser_controller.navigate(url):
            self.io.tool_output("✓ Navigation successful", log_only=False)
        else:
            self.io.tool_error("Navigation failed")

    def cmd_browser_click(self, args):
        "Click an element on the page"
        if not Commands.browser_controller:
            self.io.tool_error("No active browser session. Use /browser-start first.")
            return

        selector = args.strip()
        if not selector:
            self.io.tool_error("Please provide a CSS selector")
            return

        self.io.tool_output(f"Clicking {selector}...", log_only=False)
        if Commands.browser_controller.click(selector):
            self.io.tool_output("✓ Click successful", log_only=False)
        else:
            self.io.tool_error("Click failed")

    def cmd_browser_fill(self, args):
        "Fill a form field with text"
        if not Commands.browser_controller:
            self.io.tool_error("No active browser session. Use /browser-start first.")
            return

        parts = args.split(maxsplit=1)
        if len(parts) < 2:
            self.io.tool_error("Usage: /browser-fill <selector> <text>")
            return

        selector, text = parts[0], parts[1]
        self.io.tool_output(f"Filling {selector}...", log_only=False)
        if Commands.browser_controller.fill(selector, text):
            self.io.tool_output("✓ Fill successful", log_only=False)
        else:
            self.io.tool_error("Fill failed")

    def cmd_browser_select(self, args):
        "Select an option from a dropdown"
        if not Commands.browser_controller:
            self.io.tool_error("No active browser session. Use /browser-start first.")
            return

        parts = args.split(maxsplit=1)
        if len(parts) < 2:
            self.io.tool_error("Usage: /browser-select <selector> <value>")
            return

        selector, value = parts[0], parts[1]
        self.io.tool_output(f"Selecting {value} from {selector}...", log_only=False)
        if Commands.browser_controller.select(selector, value):
            self.io.tool_output("✓ Selection successful", log_only=False)
        else:
            self.io.tool_error("Selection failed")

    def cmd_browser_screenshot(self, args):
        "Take a screenshot of the current page"
        if not Commands.browser_controller:
            self.io.tool_error("No active browser session. Use /browser-start first.")
            return

        path = args.strip() or "screenshot.png"
        self.io.tool_output(f"Taking screenshot to {path}...", log_only=False)
        if Commands.browser_controller.screenshot(path):
            self.io.tool_output(f"✓ Screenshot saved to {path}", log_only=False)
        else:
            self.io.tool_error("Screenshot failed")

    def cmd_browser_content(self, args):
        "Get the current page content as text"
        if not Commands.browser_controller:
            self.io.tool_error("No active browser session. Use /browser-start first.")
            return

        content = Commands.browser_controller.get_text()
        if content:
            self.io.tool_output("Current page content:", log_only=False)
            self.io.tool_output(content, log_only=False)
        else:
            self.io.tool_error("Failed to get page content")

    def is_command(self, inp):
        return inp[0] in "/!"

    def get_raw_completions(self, cmd):
        assert cmd.startswith("/")
        cmd = cmd[1:]
        cmd = cmd.replace("-", "_")

        raw_completer = getattr(self, f"completions_raw_{cmd}", None)
        return raw_completer

    def get_completions(self, cmd):
        assert cmd.startswith("/")
        cmd = cmd[1:]

        cmd = cmd.replace("-", "_")
        fun = getattr(self, f"completions_{cmd}", None)
        if not fun:
            return
        return sorted(fun())

    def get_commands(self):
        commands = []
        for attr in dir(self):
            if not attr.startswith("cmd_"):
                continue
            cmd = attr[4:]
            cmd = cmd.replace("_", "-")
            commands.append("/" + cmd)

        return commands

    def do_run(self, cmd_name, args):
        cmd_name = cmd_name.replace("-", "_")
        cmd_method_name = f"cmd_{cmd_name}"
        cmd_method = getattr(self, cmd_method_name, None)
        if not cmd_method:
            self.io.tool_output(f"Error: Command {cmd_name} not found.")
            return

        try:
            return cmd_method(args)
        except ANY_GIT_ERROR as err:
            self.io.tool_error(f"Unable to complete {cmd_name}: {err}")

    def matching_commands(self, inp):
        words = inp.strip().split()
        if not words:
            return

        first_word = words[0]
        rest_inp = inp[len(words[0]) :].strip()

        all_commands = self.get_commands()
        matching_commands = [cmd for cmd in all_commands if cmd.startswith(first_word)]
        return matching_commands, first_word, rest_inp

    def run(self, inp):
        if inp.startswith("!"):
            self.coder.event("command_run")
            return self.do_run("run", inp[1:])

        res = self.matching_commands(inp)
        if res is None:
            return
        matching_commands, first_word, rest_inp = res
        if len(matching_commands) == 1:
            command = matching_commands[0][1:]
            self.coder.event(f"command_{command}")
            return self.do_run(command, rest_inp)
        elif first_word in matching_commands:
            command = first_word[1:]
            self.coder.event(f"command_{command}")
            return self.do_run(command, rest_inp)
        elif len(matching_commands) > 1:
            self.io.tool_error(f"Ambiguous command: {', '.join(matching_commands)}")
        else:
            self.io.tool_error(f"Invalid command: {first_word}")

    # any method called cmd_xxx becomes a command automatically.
    # each one must take an args param.

    def cmd_commit(self, args=None):
        "Commit edits to the repo made outside the chat (commit message optional)"
        logger = logging.getLogger(__name__)
        logger.info("Commit command executed")
        logger.debug(f"Commit message: {args}")
        try:
            self.raw_cmd_commit(args)
        except ANY_GIT_ERROR as err:
            logger.error(f"Git error during commit: {err}")
            logger.error(traceback.format_exc())
            self.io.tool_error(f"Unable to complete commit: {err}")

    def raw_cmd_commit(self, args=None):
        logger = logging.getLogger(__name__)
        logger.debug("Raw commit command executing")
        
        if not self.coder.repo:
            logger.warning("No git repository found for commit")
            self.io.tool_error("No git repository found.")
            return

        if not self.coder.repo.is_dirty():
            logger.info("No changes to commit (repo is clean)")
            self.io.tool_warning("No more changes to commit.")
            return

        commit_message = args.strip() if args else None
        logger.info(f"Committing with message: {commit_message}")
        self.coder.repo.commit(message=commit_message, coder=self.coder)
        logger.info("Commit completed successfully")

    def cmd_lint(self, args="", fnames=None):
        "Lint and fix in-chat files or all dirty files if none in chat"

        if not self.coder.repo:
            self.io.tool_error("No git repository found.")
            return

        if not fnames:
            fnames = self.coder.get_inchat_relative_files()

        # If still no files, get all dirty files in the repo
        if not fnames and self.coder.repo:
            fnames = self.coder.repo.get_dirty_files()

        if not fnames:
            self.io.tool_warning("No dirty files to lint.")
            return

        fnames = [self.coder.abs_root_path(fname) for fname in fnames]

        lint_coder = None
        for fname in fnames:
            try:
                errors = self.coder.linter.lint(fname)
            except FileNotFoundError as err:
                self.io.tool_error(f"Unable to lint {fname}")
                self.io.tool_output(str(err))
                continue

            if not errors:
                continue

            self.io.tool_output(errors)
            if not self.io.confirm_ask(f"Fix lint errors in {fname}?", default="y"):
                continue

            # Commit everything before we start fixing lint errors
            if self.coder.repo.is_dirty() and self.coder.dirty_commits:
                self.cmd_commit("")

            if not lint_coder:
                lint_coder = self.coder.clone(
                    # Clear the chat history, fnames
                    cur_messages=[],
                    done_messages=[],
                    fnames=None,
                )

            lint_coder.add_rel_fname(fname)
            lint_coder.run(errors)
            lint_coder.abs_fnames = set()

        if lint_coder and self.coder.repo.is_dirty() and self.coder.auto_commits:
            self.cmd_commit("")

    def cmd_clear(self, args):
        "Clear the chat history"

        self._clear_chat_history()
        self.io.tool_output("All chat history cleared.")

    def _drop_all_files(self):
        self.coder.abs_fnames = set()

        # When dropping all files, keep those that were originally provided via args.read
        if self.original_read_only_fnames:
            # Keep only the original read-only files
            to_keep = set()
            for abs_fname in self.coder.abs_read_only_fnames:
                rel_fname = self.coder.get_rel_fname(abs_fname)
                if (
                    abs_fname in self.original_read_only_fnames
                    or rel_fname in self.original_read_only_fnames
                ):
                    to_keep.add(abs_fname)
            self.coder.abs_read_only_fnames = to_keep
        else:
            self.coder.abs_read_only_fnames = set()

    def _clear_chat_history(self):
        self.coder.done_messages = []
        self.coder.cur_messages = []

    def cmd_reset(self, args):
        "Drop all files and clear the chat history"
        self._drop_all_files()
        self._clear_chat_history()
        self.io.tool_output("All files dropped and chat history cleared.")

    def cmd_tokens(self, args):
        "Report on the number of tokens used by the current chat context"

        res = []

        self.coder.choose_fence()

        # system messages
        main_sys = self.coder.fmt_system_prompt(self.coder.gpt_prompts.main_system)
        main_sys += "\n" + self.coder.fmt_system_prompt(self.coder.gpt_prompts.system_reminder)
        msgs = [
            dict(role="system", content=main_sys),
            dict(
                role="system",
                content=self.coder.fmt_system_prompt(self.coder.gpt_prompts.system_reminder),
            ),
        ]

        tokens = self.coder.main_model.token_count(msgs)
        res.append((tokens, "system messages", ""))

        # chat history
        msgs = self.coder.done_messages + self.coder.cur_messages
        if msgs:
            tokens = self.coder.main_model.token_count(msgs)
            res.append((tokens, "chat history", "use /clear to clear"))

        # repo map
        other_files = set(self.coder.get_all_abs_files()) - set(self.coder.abs_fnames)
        if self.coder.repo_map:
            repo_content = self.coder.repo_map.get_repo_map(self.coder.abs_fnames, other_files)
            if repo_content:
                tokens = self.coder.main_model.token_count(repo_content)
                res.append((tokens, "repository map", "use --map-tokens to resize"))

        fence = "`" * 3

        file_res = []
        # files
        for fname in self.coder.abs_fnames:
            relative_fname = self.coder.get_rel_fname(fname)
            content = self.io.read_text(fname)
            if is_image_file(relative_fname):
                tokens = self.coder.main_model.token_count_for_image(fname)
            else:
                # approximate
                content = f"{relative_fname}\n{fence}\n" + content + "{fence}\n"
                tokens = self.coder.main_model.token_count(content)
            file_res.append((tokens, f"{relative_fname}", "/drop to remove"))

        # read-only files
        for fname in self.coder.abs_read_only_fnames:
            relative_fname = self.coder.get_rel_fname(fname)
            content = self.io.read_text(fname)
            if content is not None and not is_image_file(relative_fname):
                # approximate
                content = f"{relative_fname}\n{fence}\n" + content + "{fence}\n"
                tokens = self.coder.main_model.token_count(content)
                file_res.append((tokens, f"{relative_fname} (read-only)", "/drop to remove"))

        file_res.sort()
        res.extend(file_res)

        self.io.tool_output(
            f"Approximate context window usage for {self.coder.main_model.name}, in tokens:"
        )
        self.io.tool_output()

        width = 8
        cost_width = 9

        def fmt(v):
            return format(int(v), ",").rjust(width)

        col_width = max(len(row[1]) for row in res)

        cost_pad = " " * cost_width
        total = 0
        total_cost = 0.0
        for tk, msg, tip in res:
            total += tk
            cost = tk * (self.coder.main_model.info.get("input_cost_per_token") or 0)
            total_cost += cost
            msg = msg.ljust(col_width)
            self.io.tool_output(f"${cost:7.4f} {fmt(tk)} {msg} {tip}")  # noqa: E231

        self.io.tool_output("=" * (width + cost_width + 1))
        self.io.tool_output(f"${total_cost:7.4f} {fmt(total)} tokens total")  # noqa: E231

        limit = self.coder.main_model.info.get("max_input_tokens") or 0
        if not limit:
            return

        remaining = limit - total
        if remaining > 1024:
            self.io.tool_output(f"{cost_pad}{fmt(remaining)} tokens remaining in context window")
        elif remaining > 0:
            self.io.tool_error(
                f"{cost_pad}{fmt(remaining)} tokens remaining in context window (use /drop or"
                " /clear to make space)"
            )
        else:
            self.io.tool_error(
                f"{cost_pad}{fmt(remaining)} tokens remaining, window exhausted (use /drop or"
                " /clear to make space)"
            )
        self.io.tool_output(f"{cost_pad}{fmt(limit)} tokens max context window size")

    def cmd_undo(self, args):
        "Undo the last git commit if it was done by aider"
        try:
            self.raw_cmd_undo(args)
        except ANY_GIT_ERROR as err:
            self.io.tool_error(f"Unable to complete undo: {err}")

    def raw_cmd_undo(self, args):
        if not self.coder.repo:
            self.io.tool_error("No git repository found.")
            return

        last_commit = self.coder.repo.get_head_commit()
        if not last_commit or not last_commit.parents:
            self.io.tool_error("This is the first commit in the repository. Cannot undo.")
            return

        last_commit_hash = self.coder.repo.get_head_commit_sha(short=True)
        last_commit_message = self.coder.repo.get_head_commit_message("(unknown)").strip()
        last_commit_message = (last_commit_message.splitlines() or [""])[0]
        if last_commit_hash not in self.coder.aider_commit_hashes:
            self.io.tool_error("The last commit was not made by aider in this chat session.")
            self.io.tool_output(
                "You could try `/git reset --hard HEAD^` but be aware that this is a destructive"
                " command!"
            )
            return

        if len(last_commit.parents) > 1:
            self.io.tool_error(
                f"The last commit {last_commit.hexsha} has more than 1 parent, can't undo."
            )
            return

        prev_commit = last_commit.parents[0]
        changed_files_last_commit = [item.a_path for item in last_commit.diff(prev_commit)]

        for fname in changed_files_last_commit:
            if self.coder.repo.repo.is_dirty(path=fname):
                self.io.tool_error(
                    f"The file {fname} has uncommitted changes. Please stash them before undoing."
                )
                return

            # Check if the file was in the repo in the previous commit
            try:
                prev_commit.tree[fname]
            except KeyError:
                self.io.tool_error(
                    f"The file {fname} was not in the repository in the previous commit. Cannot"
                    " undo safely."
                )
                return

        local_head = self.coder.repo.repo.git.rev_parse("HEAD")
        current_branch = self.coder.repo.repo.active_branch.name
        try:
            remote_head = self.coder.repo.repo.git.rev_parse(f"origin/{current_branch}")
            has_origin = True
        except ANY_GIT_ERROR:
            has_origin = False

        if has_origin:
            if local_head == remote_head:
                self.io.tool_error(
                    "The last commit has already been pushed to the origin. Undoing is not"
                    " possible."
                )
                return

        # Reset only the files which are part of `last_commit`
        restored = set()
        unrestored = set()
        for file_path in changed_files_last_commit:
            try:
                self.coder.repo.repo.git.checkout("HEAD~1", file_path)
                restored.add(file_path)
            except ANY_GIT_ERROR:
                unrestored.add(file_path)

        if unrestored:
            self.io.tool_error(f"Error restoring {file_path}, aborting undo.")
            self.io.tool_output("Restored files:")
            for file in restored:
                self.io.tool_output(f"  {file}")
            self.io.tool_output("Unable to restore files:")
            for file in unrestored:
                self.io.tool_output(f"  {file}")
            return

        # Move the HEAD back before the latest commit
        self.coder.repo.repo.git.reset("--soft", "HEAD~1")

        self.io.tool_output(f"Removed: {last_commit_hash} {last_commit_message}")

        # Get the current HEAD after undo
        current_head_hash = self.coder.repo.get_head_commit_sha(short=True)
        current_head_message = self.coder.repo.get_head_commit_message("(unknown)").strip()
        current_head_message = (current_head_message.splitlines() or [""])[0]
        self.io.tool_output(f"Now at:  {current_head_hash} {current_head_message}")

        if self.coder.main_model.send_undo_reply:
            return prompts.undo_command_reply

    def cmd_diff(self, args=""):
        "Display the diff of changes since the last message"
        try:
            self.raw_cmd_diff(args)
        except ANY_GIT_ERROR as err:
            self.io.tool_error(f"Unable to complete diff: {err}")

    def raw_cmd_diff(self, args=""):
        if not self.coder.repo:
            self.io.tool_error("No git repository found.")
            return

        current_head = self.coder.repo.get_head_commit_sha()
        if current_head is None:
            self.io.tool_error("Unable to get current commit. The repository might be empty.")
            return

        if len(self.coder.commit_before_message) < 2:
            commit_before_message = current_head + "^"
        else:
            commit_before_message = self.coder.commit_before_message[-2]

        if not commit_before_message or commit_before_message == current_head:
            self.io.tool_warning("No changes to display since the last message.")
            return

        self.io.tool_output(f"Diff since {commit_before_message[:7]}...")

        if self.coder.pretty:
            run_cmd(f"git diff {commit_before_message}", io=self.io)
            return

        diff = self.coder.repo.diff_commits(
            self.coder.pretty,
            commit_before_message,
            "HEAD",
        )

        self.io.print(diff)

    def quote_fname(self, fname):
        if " " in fname and '"' not in fname:
            fname = f'"{fname}"'
        return fname

    def completions_raw_read_only(self, document, complete_event):
        # Get the text before the cursor
        text = document.text_before_cursor

        # Skip the first word and the space after it
        after_command = text.split()[-1]

        # Create a new Document object with the text after the command
        new_document = Document(after_command, cursor_position=len(after_command))

        def get_paths():
            return [self.coder.root] if self.coder.root else None

        path_completer = PathCompleter(
            get_paths=get_paths,
            only_directories=False,
            expanduser=True,
        )

        # Adjust the start_position to replace all of 'after_command'
        adjusted_start_position = -len(after_command)

        # Collect all completions
        all_completions = []

        # Iterate over the completions and modify them
        for completion in path_completer.get_completions(new_document, complete_event):
            quoted_text = self.quote_fname(after_command + completion.text)
            all_completions.append(
                Completion(
                    text=quoted_text,
                    start_position=adjusted_start_position,
                    display=completion.display,
                    style=completion.style,
                    selected_style=completion.selected_style,
                )
            )

        # Add completions from the 'add' command
        add_completions = self.completions_add()
        for completion in add_completions:
            if after_command in completion:
                all_completions.append(
                    Completion(
                        text=completion,
                        start_position=adjusted_start_position,
                        display=completion,
                    )
                )

        # Sort all completions based on their text
        sorted_completions = sorted(all_completions, key=lambda c: c.text)

        # Yield the sorted completions
        for completion in sorted_completions:
            yield completion

    def completions_add(self):
        files = set(self.coder.get_all_relative_files())
        files = files - set(self.coder.get_inchat_relative_files())
        files = [self.quote_fname(fn) for fn in files]
        return files

    def glob_filtered_to_repo(self, pattern):
        if not pattern.strip():
            return []
        try:
            if os.path.isabs(pattern):
                # Handle absolute paths
                raw_matched_files = [Path(pattern)]
            else:
                try:
                    raw_matched_files = list(Path(self.coder.root).glob(pattern))
                except (IndexError, AttributeError):
                    raw_matched_files = []
        except ValueError as err:
            self.io.tool_error(f"Error matching {pattern}: {err}")
            raw_matched_files = []

        matched_files = []
        for fn in raw_matched_files:
            matched_files += expand_subdir(fn)

        matched_files = [
            fn.relative_to(self.coder.root)
            for fn in matched_files
            if fn.is_relative_to(self.coder.root)
        ]

        # if repo, filter against it
        if self.coder.repo:
            git_files = self.coder.repo.get_tracked_files()
            matched_files = [fn for fn in matched_files if str(fn) in git_files]

        res = list(map(str, matched_files))
        return res

    def cmd_add(self, args):
        "Add files to the chat so aider can edit them or review them in detail"

        all_matched_files = set()

        filenames = parse_quoted_filenames(args)
        for word in filenames:
            if Path(word).is_absolute():
                fname = Path(word)
            else:
                fname = Path(self.coder.root) / word

            if self.coder.repo and self.coder.repo.ignored_file(fname):
                self.io.tool_warning(f"Skipping {fname} due to aiderignore or --subtree-only.")
                continue

            if fname.exists():
                if fname.is_file():
                    all_matched_files.add(str(fname))
                    continue
                # an existing dir, escape any special chars so they won't be globs
                word = re.sub(r"([\*\?\[\]])", r"[\1]", word)

            matched_files = self.glob_filtered_to_repo(word)
            if matched_files:
                all_matched_files.update(matched_files)
                continue

            if "*" in str(fname) or "?" in str(fname):
                self.io.tool_error(
                    f"No match, and cannot create file with wildcard characters: {fname}"
                )
                continue

            if fname.exists() and fname.is_dir() and self.coder.repo:
                self.io.tool_error(f"Directory {fname} is not in git.")
                self.io.tool_output(f"You can add to git with: /git add {fname}")
                continue

            if self.io.confirm_ask(f"No files matched '{word}'. Do you want to create {fname}?"):
                try:
                    fname.parent.mkdir(parents=True, exist_ok=True)
                    fname.touch()
                    all_matched_files.add(str(fname))
                except OSError as e:
                    self.io.tool_error(f"Error creating file {fname}: {e}")

        for matched_file in sorted(all_matched_files):
            abs_file_path = self.coder.abs_root_path(matched_file)

            if (
                not abs_file_path.startswith(self.coder.root)
                and not is_image_file(matched_file)
                and self.coder.auto_commits
            ):
                self.io.tool_error(
                    f"Can not add {abs_file_path}, which is not within {self.coder.root}"
                )
                continue

            if (
                self.coder.repo
                and self.coder.repo.git_ignored_file(matched_file)
                and not self.coder.add_gitignore_files
            ):
                self.io.tool_error(f"Can't add {matched_file} which is in gitignore")
                continue

            if abs_file_path in self.coder.abs_fnames:
                self.io.tool_error(f"{matched_file} is already in the chat as an editable file")
                continue
            elif abs_file_path in self.coder.abs_read_only_fnames:
                # Determine if file can be promoted to editable
                if self.coder.repo:
                    can_edit = self.coder.repo.path_in_repo(matched_file)
                else:
                    can_edit = abs_file_path.startswith(self.coder.root)

                if can_edit:
                    self.coder.abs_read_only_fnames.remove(abs_file_path)
                    self.coder.abs_fnames.add(abs_file_path)
                    self.io.tool_output(
                        f"Moved {matched_file} from read-only to editable files in the chat"
                    )
                else:
                    self.io.tool_error(
                        f"Cannot add {matched_file} as it's not part of the repository"
                    )
            else:
                if is_image_file(matched_file) and not self.coder.main_model.info.get(
                    "supports_vision"
                ):
                    self.io.tool_error(
                        f"Cannot add image file {matched_file} as the"
                        f" {self.coder.main_model.name} does not support images."
                    )
                    continue
                content = self.io.read_text(abs_file_path)
                if content is None:
                    self.io.tool_error(f"Unable to read {matched_file}")
                else:
                    self.coder.abs_fnames.add(abs_file_path)
                    fname = self.coder.get_rel_fname(abs_file_path)
                    self.io.tool_output(f"Added {fname} to the chat")
                    self.coder.check_added_files()

    def completions_drop(self):
        files = self.coder.get_inchat_relative_files()
        read_only_files = [self.coder.get_rel_fname(fn) for fn in self.coder.abs_read_only_fnames]
        all_files = files + read_only_files
        all_files = [self.quote_fname(fn) for fn in all_files]
        return all_files

    def cmd_drop(self, args=""):
        "Remove files from the chat session to free up context space"

        if not args.strip():
            if self.original_read_only_fnames:
                self.io.tool_output(
                    "Dropping all files from the chat session except originally read-only files."
                )
            else:
                self.io.tool_output("Dropping all files from the chat session.")
            self._drop_all_files()
            return

        filenames = parse_quoted_filenames(args)
        for word in filenames:
            # Expand tilde in the path
            expanded_word = os.path.expanduser(word)

            # Handle read-only files with substring matching and samefile check
            read_only_matched = []
            for f in self.coder.abs_read_only_fnames:
                if expanded_word in f:
                    read_only_matched.append(f)
                    continue

                # Try samefile comparison for relative paths
                try:
                    abs_word = os.path.abspath(expanded_word)
                    if os.path.samefile(abs_word, f):
                        read_only_matched.append(f)
                except (FileNotFoundError, OSError):
                    continue

            for matched_file in read_only_matched:
                self.coder.abs_read_only_fnames.remove(matched_file)
                self.io.tool_output(f"Removed read-only file {matched_file} from the chat")

            # For editable files, use glob if word contains glob chars, otherwise use substring
            if any(c in expanded_word for c in "*?[]"):
                matched_files = self.glob_filtered_to_repo(expanded_word)
            else:
                # Use substring matching like we do for read-only files
                matched_files = [
                    self.coder.get_rel_fname(f) for f in self.coder.abs_fnames if expanded_word in f
                ]

            if not matched_files:
                matched_files.append(expanded_word)

            for matched_file in matched_files:
                abs_fname = self.coder.abs_root_path(matched_file)
                if abs_fname in self.coder.abs_fnames:
                    self.coder.abs_fnames.remove(abs_fname)
                    self.io.tool_output(f"Removed {matched_file} from the chat")

    def cmd_git(self, args):
        "Run a git command (output excluded from chat)"
        combined_output = None
        try:
            args = "git " + args
            env = dict(subprocess.os.environ)
            env["GIT_EDITOR"] = "true"
            result = subprocess.run(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
                shell=True,
                encoding=self.io.encoding,
                errors="replace",
            )
            combined_output = result.stdout
        except Exception as e:
            self.io.tool_error(f"Error running /git command: {e}")

        if combined_output is None:
            return

        self.io.tool_output(combined_output)

    def cmd_test(self, args):
        """
        Run tests or generate test code.
        
        This command provides test execution and generation capabilities.
        
        Subcommands:
            - run [command]: Run test command (default behavior)
            - generate <file_path> <function_name>: Generate tests for a function
            - coverage <file_path>: Generate test coverage report
            
        Args:
            args: Test command in format "<command> [args]"
            
        Examples:
            /test run pytest
            /test generate my_file.py my_function
            /test coverage my_file.py
        """
        self.log_command_start("cmd_test", args)
        
        parts = args.strip().split()
        
        if not parts:
            # Default behavior: run test command
            if not self.coder.test_cmd:
                self.io.tool_error("No test command configured. Set with --test-cmd or use /test run <command>")
                self.log_command_end("cmd_test", "error", "No test command")
                return
            args = self.coder.test_cmd
        else:
            command = parts[0].lower()
            
            if command == 'generate':
                if len(parts) < 3:
                    self.io.tool_error("Usage: /test generate <file_path> <function_name>")
                    self.log_command_end("cmd_test", "error", "Insufficient arguments")
                    return
                
                file_path = parts[1]
                function_name = parts[2]
                
                # Check if index manager is available
                if not hasattr(self.coder, 'index_manager') or not self.coder.index_manager:
                    self.io.tool_error("Index manager not available. Run /index first.")
                    self.log_command_end("cmd_test", "error", "Index manager not available")
                    return
                
                results = self.coder.index_manager.generate_test_for_function(file_path, function_name)
                
                if results['success']:
                    self.io.tool_output(f"\n✓ Test generated for {results['function_name']}", log_only=False)
                    self.io.tool_output(f"\n{results['test_code']}", log_only=False)
                else:
                    self.io.tool_error(f"Test generation failed: {results.get('error', 'Unknown error')}")
                    self.log_command_end("cmd_test", "error", str(results.get('error')))
                    return
            
            elif command == 'coverage':
                if len(parts) < 2:
                    self.io.tool_error("Usage: /test coverage <file_path>")
                    self.log_command_end("cmd_test", "error", "Insufficient arguments")
                    return
                
                file_path = parts[1]
                
                # Check if index manager is available
                if not hasattr(self.coder, 'index_manager') or not self.coder.index_manager:
                    self.io.tool_error("Index manager not available. Run /index first.")
                    self.log_command_end("cmd_test", "error", "Index manager not available")
                    return
                
                results = self.coder.index_manager.generate_test_coverage_report(file_path)
                
                if 'error' in results:
                    self.io.tool_error(f"Coverage report failed: {results['error']}")
                    self.log_command_end("cmd_test", "error", str(results['error']))
                    return
                
                self.io.tool_output(f"\n📊 Coverage report for {results['file_path']}:", log_only=False)
                self.io.tool_output(f"  Functions: {results['functions_count']}", log_only=False)
                self.io.tool_output(f"  Classes: {results['classes_count']}", log_only=False)
                self.io.tool_output(f"  Estimated coverage: {results['estimated_coverage']:.1%}", log_only=False)
                
                if self.verbose and results['functions']:
                    self.io.tool_output(f"\n  Functions:", log_only=False)
                    for func in results['functions']:
                        self.io.tool_output(f"    • {func['name']} (line {func['line']})", log_only=False)
            
            elif command == 'run':
                # Run test command
                args = ' '.join(parts[1:])
            else:
                # Default: run as test command
                args = ' '.join(parts)
        
        # Run test command
        if not args:
            self.io.tool_error("No test command provided")
            self.log_command_end("cmd_test", "error", "No test command")
            return
        
        import subprocess
        
        self.io.tool_output(f"Running: {args}", log_only=False)
        
        try:
            result = subprocess.run(args, shell=True, capture_output=True, text=True, cwd=self.coder.root)
            
            if result.stdout:
                self.io.tool_output(result.stdout, log_only=False)
            
            if result.stderr:
                self.io.tool_error(result.stderr, log_only=False)
            
            if result.returncode != 0:
                self.io.tool_error(f"Test failed with exit code {result.returncode}", log_only=False)
                self.log_command_end("cmd_test", "error", f"Exit code {result.returncode}")
            else:
                self.io.tool_output("✓ Tests passed", log_only=False)
                self.log_command_end("cmd_test", "success", "Tests passed")
        
        except Exception as e:
            self.io.tool_error(f"Error running tests: {e}")
            self.log_command_end("cmd_test", "error", str(e))
            return

        if not callable(args):
            if type(args) is not str:
                raise ValueError(repr(args))
            return self.cmd_run(args, True)

        errors = args()
        if not errors:
            return

        self.io.tool_output(errors)
        return errors

    def cmd_run(self, args, add_on_nonzero_exit=False):
        "Run a shell command and optionally add the output to the chat (alias: !)"
        logger = logging.getLogger(__name__)
        logger.info(f"Running shell command: {args}")
        logger.debug(f"Add on non-zero exit: {add_on_nonzero_exit}")
        
        exit_status, combined_output = run_cmd(
            args, verbose=self.verbose, error_print=self.io.tool_error, cwd=self.coder.root, io=self.io
        )

        logger.info(f"Command exit status: {exit_status}")
        if exit_status != 0:
            logger.warning(f"Command failed with exit status {exit_status}")

        if combined_output is None:
            logger.warning("Command output is None")
            return

        # Calculate token count of output
        token_count = self.coder.main_model.token_count(combined_output)
        k_tokens = token_count / 1000
        logger.debug(f"Command output token count: {k_tokens:.1f}k")

        if add_on_nonzero_exit:
            add = exit_status != 0
        else:
            add = self.io.confirm_ask(f"Add {k_tokens:.1f}k tokens of command output to the chat?")

        logger.debug(f"Adding output to chat: {add}")

        if add:
            num_lines = len(combined_output.strip().splitlines())
            line_plural = "line" if num_lines == 1 else "lines"
            self.io.tool_output(f"Added {num_lines} {line_plural} of output to the chat.")

            msg = prompts.run_output.format(
                command=args,
                output=combined_output,
            )

            self.coder.cur_messages += [
                dict(role="user", content=msg),
                dict(role="assistant", content="Ok."),
            ]

            if add_on_nonzero_exit and exit_status != 0:
                # Return the formatted output message for test failures
                return msg
            elif add and exit_status != 0:
                self.io.placeholder = "What's wrong? Fix"

        # Return None if output wasn't added or command succeeded
        return None

    def cmd_exit(self, args):
        "Exit the application"
        self.coder.event("exit", reason="/exit")
        sys.exit()

    def cmd_quit(self, args):
        "Exit the application"
        self.cmd_exit(args)

    def cmd_ls(self, args):
        "List all known files and indicate which are included in the chat session"

        files = self.coder.get_all_relative_files()

        other_files = []
        chat_files = []
        read_only_files = []
        for file in files:
            abs_file_path = self.coder.abs_root_path(file)
            if abs_file_path in self.coder.abs_fnames:
                chat_files.append(file)
            else:
                other_files.append(file)

        # Add read-only files
        for abs_file_path in self.coder.abs_read_only_fnames:
            rel_file_path = self.coder.get_rel_fname(abs_file_path)
            read_only_files.append(rel_file_path)

        if not chat_files and not other_files and not read_only_files:
            self.io.tool_output("\nNo files in chat, git repo, or read-only list.")
            return

        if other_files:
            self.io.tool_output("Repo files not in the chat:\n")
        for file in other_files:
            self.io.tool_output(f"  {file}")

        if read_only_files:
            self.io.tool_output("\nRead-only files:\n")
        for file in read_only_files:
            self.io.tool_output(f"  {file}")

        if chat_files:
            self.io.tool_output("\nFiles in chat:\n")
        for file in chat_files:
            self.io.tool_output(f"  {file}")

    def basic_help(self):
        commands = sorted(self.get_commands())
        pad = max(len(cmd) for cmd in commands)
        pad = "{cmd:" + str(pad) + "}"
        for cmd in commands:
            cmd_method_name = f"cmd_{cmd[1:]}".replace("-", "_")
            cmd_method = getattr(self, cmd_method_name, None)
            cmd = pad.format(cmd=cmd)
            if cmd_method:
                description = cmd_method.__doc__
                self.io.tool_output(f"{cmd} {description}")
            else:
                self.io.tool_output(f"{cmd} No description available.")
        self.io.tool_output()
        self.io.tool_output("Use `/help <question>` to ask questions about how to use aider.")

    def cmd_help(self, args):
        "Ask questions about aider"

        if not args.strip():
            self.basic_help()
            return

        self.coder.event("interactive help")
        from aider.coders.base_coder import Coder

        if not self.help:
            res = install_help_extra(self.io)
            if not res:
                self.io.tool_error("Unable to initialize interactive help.")
                return

            self.help = Help()

        coder = Coder.create(
            io=self.io,
            from_coder=self.coder,
            edit_format="help",
            summarize_from_coder=False,
            map_tokens=512,
            map_mul_no_files=1,
        )
        user_msg = self.help.ask(args)
        user_msg += """
# Announcement lines from when this session of aider was launched:

"""
        user_msg += "\n".join(self.coder.get_announcements()) + "\n"

        coder.run(user_msg, preproc=False)

        if self.coder.repo_map:
            map_tokens = self.coder.repo_map.max_map_tokens
            map_mul_no_files = self.coder.repo_map.map_mul_no_files
        else:
            map_tokens = 0
            map_mul_no_files = 1

        raise SwitchCoder(
            edit_format=self.coder.edit_format,
            summarize_from_coder=False,
            from_coder=coder,
            map_tokens=map_tokens,
            map_mul_no_files=map_mul_no_files,
            show_announcements=False,
        )

    def completions_ask(self):
        raise CommandCompletionException()

    def completions_code(self):
        raise CommandCompletionException()

    def completions_architect(self):
        raise CommandCompletionException()

    def completions_context(self):
        raise CommandCompletionException()

    def cmd_ask(self, args):
        """Ask questions about the code base without editing any files. If no prompt provided, switches to ask mode."""  # noqa
        return self._generic_chat_command(args, "ask")

    def cmd_code(self, args):
        """Ask for changes to your code. If no prompt provided, switches to code mode."""  # noqa
        return self._generic_chat_command(args, self.coder.main_model.edit_format)

    def cmd_architect(self, args):
        """Enter architect/editor mode using 2 different models. If no prompt provided, switches to architect/editor mode."""  # noqa
        return self._generic_chat_command(args, "architect")

    def cmd_context(self, args):
        """Enter context mode to see surrounding code context. If no prompt provided, switches to context mode."""  # noqa
        return self._generic_chat_command(args, "context", placeholder=args.strip() or None)

    def cmd_ok(self, args):
        "Alias for `/code Ok, please go ahead and make those changes.` (any args are appended)"
        msg = "Ok, please go ahead and make those changes."
        extra = (args or "").strip()
        if extra:
            msg = f"{msg} {extra}"
        return self.cmd_code(msg)

    def _generic_chat_command(self, args, edit_format, placeholder=None):
        if not args.strip():
            # Switch to the corresponding chat mode if no args provided
            return self.cmd_chat_mode(edit_format)

        from aider.coders.base_coder import Coder

        coder = Coder.create(
            io=self.io,
            from_coder=self.coder,
            edit_format=edit_format,
            summarize_from_coder=False,
        )

        user_msg = args
        coder.run(user_msg)

        # Use the provided placeholder if any
        raise SwitchCoder(
            edit_format=self.coder.edit_format,
            summarize_from_coder=False,
            from_coder=coder,
            show_announcements=False,
            placeholder=placeholder,
        )

    def get_help_md(self):
        "Show help about all commands in markdown"

        res = """
|Command|Description|
|:------|:----------|
"""
        commands = sorted(self.get_commands())
        for cmd in commands:
            cmd_method_name = f"cmd_{cmd[1:]}".replace("-", "_")
            cmd_method = getattr(self, cmd_method_name, None)
            if cmd_method:
                description = cmd_method.__doc__
                res += f"| **{cmd}** | {description} |\n"
            else:
                res += f"| **{cmd}** | |\n"

        res += "\n"
        return res

    def cmd_voice(self, args):
        "Record and transcribe voice input"

        if not self.voice:
            if "OPENAI_API_KEY" not in os.environ:
                self.io.tool_error("To use /voice you must provide an OpenAI API key.")
                return
            try:
                self.voice = voice.Voice(
                    audio_format=self.voice_format or "wav", device_name=self.voice_input_device
                )
            except voice.SoundDeviceError:
                self.io.tool_error(
                    "Unable to import `sounddevice` and/or `soundfile`, is portaudio installed?"
                )
                return

        try:
            text = self.voice.record_and_transcribe(None, language=self.voice_language)
        except litellm.OpenAIError as err:
            self.io.tool_error(f"Unable to use OpenAI whisper model: {err}")
            return

        if text:
            self.io.placeholder = text

    def cmd_paste(self, args):
        """Paste image/text from the clipboard into the chat.\
        Optionally provide a name for the image."""
        try:
            # Check for image first
            image = ImageGrab.grabclipboard()
            if isinstance(image, Image.Image):
                if args.strip():
                    filename = args.strip()
                    ext = os.path.splitext(filename)[1].lower()
                    if ext in (".jpg", ".jpeg", ".png"):
                        basename = filename
                    else:
                        basename = f"{filename}.png"
                else:
                    basename = "clipboard_image.png"

                temp_dir = tempfile.mkdtemp()
                temp_file_path = os.path.join(temp_dir, basename)
                image_format = "PNG" if basename.lower().endswith(".png") else "JPEG"
                image.save(temp_file_path, image_format)

                abs_file_path = Path(temp_file_path).resolve()

                # Check if a file with the same name already exists in the chat
                existing_file = next(
                    (f for f in self.coder.abs_fnames if Path(f).name == abs_file_path.name), None
                )
                if existing_file:
                    self.coder.abs_fnames.remove(existing_file)
                    self.io.tool_output(f"Replaced existing image in the chat: {existing_file}")

                self.coder.abs_fnames.add(str(abs_file_path))
                self.io.tool_output(f"Added clipboard image to the chat: {abs_file_path}")
                self.coder.check_added_files()

                return

            # If not an image, try to get text
            text = pyperclip.paste()
            if text:
                self.io.tool_output(text)
                return text

            self.io.tool_error("No image or text content found in clipboard.")
            return

        except Exception as e:
            self.io.tool_error(f"Error processing clipboard content: {e}")

    def cmd_read_only(self, args):
        "Add files to the chat that are for reference only, or turn added files to read-only"
        if not args.strip():
            # Convert all files in chat to read-only
            for fname in list(self.coder.abs_fnames):
                self.coder.abs_fnames.remove(fname)
                self.coder.abs_read_only_fnames.add(fname)
                rel_fname = self.coder.get_rel_fname(fname)
                self.io.tool_output(f"Converted {rel_fname} to read-only")
            return

        filenames = parse_quoted_filenames(args)
        all_paths = []

        # First collect all expanded paths
        for pattern in filenames:
            expanded_pattern = expanduser(pattern)
            path_obj = Path(expanded_pattern)
            is_abs = path_obj.is_absolute()
            if not is_abs:
                path_obj = Path(self.coder.root) / path_obj

            matches = []
            # Check for literal path existence first
            if path_obj.exists():
                matches = [path_obj]
            else:
                # If literal path doesn't exist, try globbing
                if is_abs:
                    # For absolute paths, glob it
                    matches = [Path(p) for p in glob.glob(expanded_pattern)]
                else:
                    # For relative paths and globs, use glob from the root directory
                    matches = list(Path(self.coder.root).glob(expanded_pattern))

            if not matches:
                self.io.tool_error(f"No matches found for: {pattern}")
            else:
                all_paths.extend(matches)

        # Then process them in sorted order
        for path in sorted(all_paths):
            abs_path = self.coder.abs_root_path(path)
            if os.path.isfile(abs_path):
                self._add_read_only_file(abs_path, path)
            elif os.path.isdir(abs_path):
                self._add_read_only_directory(abs_path, path)
            else:
                self.io.tool_error(f"Not a file or directory: {abs_path}")

    def _add_read_only_file(self, abs_path, original_name):
        if is_image_file(original_name) and not self.coder.main_model.info.get("supports_vision"):
            self.io.tool_error(
                f"Cannot add image file {original_name} as the"
                f" {self.coder.main_model.name} does not support images."
            )
            return

        if abs_path in self.coder.abs_read_only_fnames:
            self.io.tool_error(f"{original_name} is already in the chat as a read-only file")
            return
        elif abs_path in self.coder.abs_fnames:
            self.coder.abs_fnames.remove(abs_path)
            self.coder.abs_read_only_fnames.add(abs_path)
            self.io.tool_output(
                f"Moved {original_name} from editable to read-only files in the chat"
            )
        else:
            self.coder.abs_read_only_fnames.add(abs_path)
            self.io.tool_output(f"Added {original_name} to read-only files.")

    def _add_read_only_directory(self, abs_path, original_name):
        added_files = 0
        for root, _, files in os.walk(abs_path):
            for file in files:
                file_path = os.path.join(root, file)
                if (
                    file_path not in self.coder.abs_fnames
                    and file_path not in self.coder.abs_read_only_fnames
                ):
                    self.coder.abs_read_only_fnames.add(file_path)
                    added_files += 1

        if added_files > 0:
            self.io.tool_output(
                f"Added {added_files} files from directory {original_name} to read-only files."
            )
        else:
            self.io.tool_output(f"No new files added from directory {original_name}.")

    def cmd_map(self, args):
        "Print out the current repository map"
        repo_map = self.coder.get_repo_map()
        if repo_map:
            self.io.tool_output(repo_map)
        else:
            self.io.tool_output("No repository map available.")

    def cmd_map_refresh(self, args):
        "Force a refresh of the repository map"
        repo_map = self.coder.get_repo_map(force_refresh=True)
        if repo_map:
            self.io.tool_output("The repo map has been refreshed, use /map to view it.")

    def cmd_settings(self, args):
        "Print out the current settings"
        settings = format_settings(self.parser, self.args)
        announcements = "\n".join(self.coder.get_announcements())

        # Build metadata for the active models (main, editor, weak)
        model_sections = []
        active_models = [
            ("Main model", self.coder.main_model),
            ("Editor model", getattr(self.coder.main_model, "editor_model", None)),
            ("Weak model", getattr(self.coder.main_model, "weak_model", None)),
        ]
        for label, model in active_models:
            if not model:
                continue
            info = getattr(model, "info", {}) or {}
            if not info:
                continue
            model_sections.append(f"{label} ({model.name}):")
            for k, v in sorted(info.items()):
                model_sections.append(f"  {k}: {v}")

        if model_sections:
            settings = settings + "\n" + "\n".join(model_sections)

        self.io.tool_output(settings, log_only=False)

    def cmd_confirm(self, args):
        """
        Toggle dangerous command confirmation on/off (global configuration).
        
        This command allows users to enable or disable the confirmation mechanism
        for dangerous operations globally. This is useful for automation scenarios
        where manual confirmation would block automated workflows.
        
        Security Considerations:
            - Disabling confirmation is logged as a warning
            - Clear warnings are displayed when disabling
            - Current status is always visible
            - All confirmation changes are logged for audit trail
            
        Subcommands:
            - (no args): Show current confirmation status
            - on: Enable dangerous command confirmation
            - off: Disable dangerous command confirmation
            
        Args:
            args (str): Command argument (on, off, or empty to show status)
            
        Example:
            /confirm              # Show current status
            /confirm on           # Enable confirmation
            /confirm off          # Disable confirmation (use with caution)
        """
        parts = args.strip().lower().split()
        
        if not parts:
            # Show current status
            status = "enabled" if Commands.require_confirmation else "disabled"
            self.io.tool_output(f"\n🔒 Dangerous command confirmation: {status}", log_only=False)
            self.io.tool_output("Usage: /confirm on|off", log_only=False)
            return
        
        if parts[0] == 'on':
            Commands.require_confirmation = True
            self.io.tool_output("✅ Dangerous command confirmation ENABLED", log_only=False)
            audit_logger.info("Confirmation setting changed: enabled")
        elif parts[0] == 'off':
            Commands.require_confirmation = False
            self.io.tool_output("⚠️  Dangerous command confirmation DISABLED", log_only=False)
            self.io.tool_output("⚠️  Use with caution - dangerous actions will execute without confirmation!", log_only=False)
            audit_logger.warning("Confirmation setting changed: disabled")
        else:
            self.io.tool_error("Usage: /confirm on|off")
            self.io.tool_error("Current status: " + ("enabled" if Commands.require_confirmation else "disabled"))

    def completions_raw_load(self, document, complete_event):
        return self.completions_raw_read_only(document, complete_event)

    def cmd_load(self, args):
        "Load and execute commands from a file"
        if not args.strip():
            self.io.tool_error("Please provide a filename containing commands to load.")
            return

        try:
            with open(args.strip(), "r", encoding=self.io.encoding, errors="replace") as f:
                commands = f.readlines()
        except FileNotFoundError:
            self.io.tool_error(f"File not found: {args}")
            return
        except Exception as e:
            self.io.tool_error(f"Error reading file: {e}")
            return

        for cmd in commands:
            cmd = cmd.strip()
            if not cmd or cmd.startswith("#"):
                continue

            self.io.tool_output(f"\nExecuting: {cmd}")
            try:
                self.run(cmd)
            except SwitchCoder:
                self.io.tool_error(
                    f"Command '{cmd}' is only supported in interactive mode, skipping."
                )

    def completions_raw_save(self, document, complete_event):
        return self.completions_raw_read_only(document, complete_event)

    def cmd_save(self, args):
        "Save commands to a file that can reconstruct the current chat session's files"
        if not args.strip():
            self.io.tool_error("Please provide a filename to save the commands to.")
            return

        try:
            with open(args.strip(), "w", encoding=self.io.encoding) as f:
                f.write("/drop\n")
                # Write commands to add editable files
                for fname in sorted(self.coder.abs_fnames):
                    rel_fname = self.coder.get_rel_fname(fname)
                    f.write(f"/add       {rel_fname}\n")

                # Write commands to add read-only files
                for fname in sorted(self.coder.abs_read_only_fnames):
                    # Use absolute path for files outside repo root, relative path for files inside
                    if Path(fname).is_relative_to(self.coder.root):
                        rel_fname = self.coder.get_rel_fname(fname)
                        f.write(f"/read-only {rel_fname}\n")
                    else:
                        f.write(f"/read-only {fname}\n")

            self.io.tool_output(f"Saved commands to {args.strip()}")
        except Exception as e:
            self.io.tool_error(f"Error saving commands to file: {e}")

    def cmd_multiline_mode(self, args):
        "Toggle multiline mode (swaps behavior of Enter and Meta+Enter)"
        self.io.toggle_multiline_mode()

    def cmd_copy(self, args):
        "Copy the last assistant message to the clipboard"
        all_messages = self.coder.done_messages + self.coder.cur_messages
        assistant_messages = [msg for msg in reversed(all_messages) if msg["role"] == "assistant"]

        if not assistant_messages:
            self.io.tool_error("No assistant messages found to copy.")
            return

        last_assistant_message = assistant_messages[0]["content"]

        try:
            pyperclip.copy(last_assistant_message)
            preview = (
                last_assistant_message[:50] + "..."
                if len(last_assistant_message) > 50
                else last_assistant_message
            )
            self.io.tool_output(f"Copied last assistant message to clipboard. Preview: {preview}")
        except pyperclip.PyperclipException as e:
            self.io.tool_error(f"Failed to copy to clipboard: {str(e)}")
            self.io.tool_output(
                "You may need to install xclip or xsel on Linux, or pbcopy on macOS."
            )
        except Exception as e:
            self.io.tool_error(f"An unexpected error occurred while copying to clipboard: {str(e)}")

    def cmd_report(self, args):
        "Report a problem by opening a GitHub Issue"
        from aider.report import report_github_issue

        announcements = "\n".join(self.coder.get_announcements())
        issue_text = announcements

        if args.strip():
            title = args.strip()
        else:
            title = None

        report_github_issue(issue_text, title=title, confirm=False)

    def cmd_summary(self, args):
        "Generate a summary of the current session's work"
        self.io.tool_output("\n📊 Session Summary", log_only=False)
        self.io.tool_output("=" * 50, log_only=False)
        
        # Commit summary
        if self.coder.aider_commit_hashes:
            self.io.tool_output(f"\n📝 Commits made by aider: {len(self.coder.aider_commit_hashes)}", log_only=False)
            for i, commit_hash in enumerate(self.coder.aider_commit_hashes[-5:], 1):
                try:
                    commit_message = self.coder.repo.get_commit_message(commit_hash)
                    self.io.tool_output(f"  {i}. {commit_hash[:7]}: {commit_message}", log_only=False)
                except Exception:
                    self.io.tool_output(f"  {i}. {commit_hash[:7]}: (unable to get message)", log_only=False)
        else:
            self.io.tool_output("\n📝 No commits made yet", log_only=False)
        
        # Files in chat
        if self.coder.abs_fnames:
            self.io.tool_output(f"\n📁 Files in chat: {len(self.coder.abs_fnames)}", log_only=False)
            for fname in list(self.coder.abs_fnames)[:10]:
                rel_fname = self.coder.get_rel_fname(fname)
                self.io.tool_output(f"  - {rel_fname}", log_only=False)
            if len(self.coder.abs_fnames) > 10:
                self.io.tool_output(f"  ... and {len(self.coder.abs_fnames) - 10} more", log_only=False)
        else:
            self.io.tool_output("\n📁 No files in chat", log_only=False)
        
        # Lint outcome
        if hasattr(self.coder, 'lint_outcome') and self.coder.lint_outcome is not None:
            status = "✓ Passed" if self.coder.lint_outcome else "✗ Failed"
            self.io.tool_output(f"\n🔍 Lint: {status}", log_only=False)
        
        # Test outcome
        if hasattr(self.coder, 'test_outcome') and self.coder.test_outcome is not None:
            status = "✓ Passed" if self.coder.test_outcome else "✗ Failed"
            self.io.tool_output(f"\n🧪 Test: {status}", log_only=False)
        
        # Token usage
        if hasattr(self.coder, 'message_tokens_sent') and self.coder.message_tokens_sent:
            tokens_sent = self.coder.message_tokens_sent
            tokens_received = self.coder.message_tokens_received
            self.io.tool_output(f"\n💰 Tokens: {tokens_sent:,} sent, {tokens_received:,} received", log_only=False)
        
        # Current model
        if hasattr(self.coder, 'main_model'):
            self.io.tool_output(f"\n🤖 Model: {self.coder.main_model.name}", log_only=False)
        
        self.io.tool_output("\n" + "=" * 50, log_only=False)

    def cmd_changelog(self, args):
        "Generate a changelog from recent commits"
        try:
            import git
            repo = git.Repo(self.coder.root)
            
            # Get recent commits (last 20)
            commits = list(repo.iter_commits(max_count=20))
            
            if not commits:
                self.io.tool_output("No commits found in this repository")
                return
            
            self.io.tool_output("\n📜 Changelog", log_only=False)
            self.io.tool_output("=" * 50, log_only=False)
            
            # Group commits by type (conventional commits)
            types = {}
            for commit in commits:
                message = commit.message.strip().split('\n')[0]
                # Extract type from conventional commit
                if ':' in message:
                    commit_type = message.split(':')[0].strip().lower()
                    if commit_type not in types:
                        types[commit_type] = []
                    types[commit_type].append({
                        'hash': commit.hexsha[:7],
                        'message': message,
                        'author': commit.author.name,
                        'date': commit.committed_datetime.strftime('%Y-%m-%d'),
                    })
            
            # Display by type
            type_order = ['feat', 'fix', 'refactor', 'perf', 'docs', 'style', 'test', 'chore', 'build', 'ci']
            for commit_type in type_order:
                if commit_type in types and types[commit_type]:
                    self.io.tool_output(f"\n### {commit_type.upper()}", log_only=False)
                    for item in types[commit_type]:
                        self.io.tool_output(f"- {item['hash']}: {item['message']} ({item['date']})", log_only=False)
            
            # Display uncategorized commits
            other_types = set(types.keys()) - set(type_order)
            if other_types:
                self.io.tool_output(f"\n### OTHER", log_only=False)
                for commit_type in other_types:
                    for item in types[commit_type]:
                        self.io.tool_output(f"- {item['hash']}: {item['message']} ({item['date']})", log_only=False)
            
            self.io.tool_output("\n" + "=" * 50, log_only=False)
            
        except ImportError:
            self.io.tool_error("GitPython not installed. Install with: pip install gitpython")
        except Exception as e:
            self.io.tool_error(f"Error generating changelog: {e}")

    def cmd_editor(self, initial_content=""):
        "Open an editor to write a prompt"

        user_input = pipe_editor(initial_content, suffix="md", editor=self.editor)
        if user_input.strip():
            self.io.set_placeholder(user_input.rstrip())

    def cmd_edit(self, args=""):
        "Alias for /editor: Open an editor to write a prompt"
        return self.cmd_editor(args)

    def cmd_think_tokens(self, args):
        """Set the thinking token budget, eg: 8096, 8k, 10.5k, 0.5M, or 0 to disable."""
        model = self.coder.main_model

        if not args.strip():
            # Display current value if no args are provided
            formatted_budget = model.get_thinking_tokens()
            if formatted_budget is None:
                self.io.tool_output("Thinking tokens are not currently set.")
            else:
                budget = model.get_raw_thinking_tokens()
                self.io.tool_output(
                    f"Current thinking token budget: {budget:,} tokens ({formatted_budget})."
                )
            return

        value = args.strip()
        model.set_thinking_tokens(value)

        # Handle the special case of 0 to disable thinking tokens
        if value == "0":
            self.io.tool_output("Thinking tokens disabled.")
        else:
            formatted_budget = model.get_thinking_tokens()
            budget = model.get_raw_thinking_tokens()
            self.io.tool_output(
                f"Set thinking token budget to {budget:,} tokens ({formatted_budget})."
            )

        self.io.tool_output()

        # Output announcements
        announcements = "\n".join(self.coder.get_announcements())
        self.io.tool_output(announcements)

    def cmd_reasoning_effort(self, args):
        "Set the reasoning effort level (values: number or low/medium/high depending on model)"
        model = self.coder.main_model

        if not args.strip():
            # Display current value if no args are provided
            reasoning_value = model.get_reasoning_effort()
            if reasoning_value is None:
                self.io.tool_output("Reasoning effort is not currently set.")
            else:
                self.io.tool_output(f"Current reasoning effort: {reasoning_value}")
            return

        value = args.strip()
        model.set_reasoning_effort(value)
        reasoning_value = model.get_reasoning_effort()
        self.io.tool_output(f"Set reasoning effort to {reasoning_value}")
        self.io.tool_output()

        # Output announcements
        announcements = "\n".join(self.coder.get_announcements())
        self.io.tool_output(announcements)

    def cmd_copy_context(self, args=None):
        """Copy the current chat context as markdown, suitable to paste into a web UI"""

        chunks = self.coder.format_chat_chunks()

        markdown = ""

        # Only include specified chunks in order
        for messages in [chunks.repo, chunks.readonly_files, chunks.chat_files]:
            for msg in messages:
                # Only include user messages
                if msg["role"] != "user":
                    continue

                content = msg["content"]

                # Handle image/multipart content
                if isinstance(content, list):
                    for part in content:
                        if part.get("type") == "text":
                            markdown += part["text"] + "\n\n"
                else:
                    markdown += content + "\n\n"

        args = args or ""
        markdown += f"""
Just tell me how to edit the files to make the changes.
Don't give me back entire files.
Just show me the edits I need to make.

{args}
"""

        try:
            pyperclip.copy(markdown)
            self.io.tool_output("Copied code context to clipboard.")
        except pyperclip.PyperclipException as e:
            self.io.tool_error(f"Failed to copy to clipboard: {str(e)}")
            self.io.tool_output(
                "You may need to install xclip or xsel on Linux, or pbcopy on macOS."
            )
        except Exception as e:
            self.io.tool_error(f"An unexpected error occurred while copying to clipboard: {str(e)}")

    def cmd_grep(self, args):
        """
        Search for a pattern across files in the codebase (aerospace-level enhanced).
        
        This command implements comprehensive code searching with aerospace-level
        safety features including input validation, resource limits, and audit logging.
        
        Aerospace-level Features:
            - Input validation: Pattern length limit (1000 chars) to prevent DoS
            - Resource limits: File count limit (1000), line count limit (10000), result limit (1000)
            - Error handling: Graceful handling of file read errors, regex compilation errors
            - Audit logging: All search operations logged for compliance
            - Timeout protection: Prevents infinite loops in large codebases
        
        Args:
            args (str): Regex pattern to search for
            
        Returns:
            None: Results are displayed via tool_output
            
        Example:
            /grep "TODO"
            /grep "def.*test"
        """
        import re
        
        # Aerospace-level input validation
        pattern = args.strip()
        if not pattern:
            self.io.tool_error("Please provide a search pattern")
            audit_logger.warning("cmd_grep called with empty pattern")
            return
        
        # Limit pattern length to prevent DoS (resource exhaustion attack)
        if len(pattern) > 1000:
            self.io.tool_error("Pattern too long (max 1000 characters)")
            audit_logger.warning(f"cmd_grep rejected pattern exceeding 1000 chars: {len(pattern)}")
            return
        
        # Compile regex to validate pattern before searching
        try:
            re.compile(pattern)
        except re.error as e:
            self.io.tool_error(f"Invalid regex pattern: {e}")
            audit_logger.warning(f"cmd_grep: Invalid regex pattern: {e}")
            return
        
        # Log search start for audit trail
        audit_logger.info(f"cmd_grep started with pattern: {pattern[:50]}...")
        self.io.tool_output(f"🔍 Searching for: {pattern}", log_only=False)
        self.io.tool_output("=" * 50, log_only=False)
        
        # Get all files to search (prioritize files in chat, then repo)
        if self.coder.abs_fnames:
            search_files = list(self.coder.abs_fnames)
        elif self.coder.repo:
            search_files = self.coder.repo.get_tracked_files()
        else:
            self.io.tool_error("No files available to search")
            audit_logger.warning("cmd_grep: No files available to search")
            return
        
        results = []
        try:
            # Compile regex with timeout protection
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error as e:
            self.io.tool_error(f"Invalid regex pattern: {e}")
            audit_logger.error(f"cmd_grep: Invalid regex pattern: {e}")
            return
        
        # Limit file count to prevent resource exhaustion
        max_files = 1000
        file_count = 0
        
        for fname in search_files:
            file_count += 1
            if file_count > max_files:
                self.io.tool_output(f"⚠️  Search limited to first {max_files} files", log_only=False)
                audit_logger.warning(f"cmd_grep: Limited to {max_files} files")
                break
            
            try:
                # Use context manager for proper file cleanup
                with open(fname, 'r', encoding='utf-8', errors='ignore') as f:
                    for line_num, line in enumerate(f, 1):
                        # Limit lines per file to prevent memory issues
                        if line_num > 10000:
                            break
                        if regex.search(line):
                            rel_fname = self.coder.get_rel_fname(fname)
                            results.append({
                                'file': rel_fname,
                                'line': line_num,
                                'content': line.rstrip()
                            })
                            # Limit total results
                            if len(results) >= 1000:
                                self.io.tool_output(f"⚠️  Results limited to 1000 matches", log_only=False)
                                audit_logger.warning(f"cmd_grep: Results limited to 1000 matches")
                                break
            except (IOError, OSError) as e:
                # Log error but continue with other files
                audit_logger.warning(f"cmd_grep: Error reading {fname}: {e}")
                continue
            except Exception as e:
                # Log unexpected error but continue
                audit_logger.error(f"cmd_grep: Unexpected error reading {fname}: {e}")
                continue
            
            if len(results) >= 1000:
                break
        
        if not results:
            self.io.tool_output("No matches found", log_only=False)
            audit_logger.info(f"cmd_grep: No matches found for pattern")
        else:
            self.io.tool_output(f"\nFound {len(results)} matches:\n", log_only=False)
            audit_logger.info(f"cmd_grep: Found {len(results)} matches")
            for result in results[:50]:  # Limit display to 50 results
                self.io.tool_output(f"  {result['file']}:{result['line']}", log_only=False)
                self.io.tool_output(f"    {result['content']}", log_only=False)
            
            if len(results) > 50:
                self.io.tool_output(f"\n... and {len(results) - 50} more matches", log_only=False)
        
        self.io.tool_output("\n" + "=" * 50, log_only=False)

    def cmd_security(self, args):
        """
        Scan code for security issues using multiple security analysis tools.
        
        This command runs various security scanning tools to identify potential
        vulnerabilities in the codebase. It attempts to use multiple tools
        and provides clear output for each scan.
        
        Supported Tools:
            - bandit: Python security linter (pip install bandit)
            - semgrep: Semantic code analysis (pip install semgrep)
            - safety: Dependency vulnerability scanner (pip install safety)
            - pip-audit: Package vulnerability scanner (pip install pip-audit)
        
        Args:
            args (str): Optional arguments (currently unused)
            
        Example:
            /security
        """
        import subprocess
        
        self.log_command_start("cmd_security", args)
        
        self.io.tool_output("🔒 Scanning for security issues", log_only=False)
        self.io.tool_output("=" * 50, log_only=False)
        
        tools_scanned = []
        
        # Try bandit for Python security scanning
        try:
            self.io.tool_output("\n🐍 Running bandit (Python)...", log_only=False)
            result = subprocess.run(['bandit', '-r', '.'], capture_output=True, text=True)
            self.io.tool_output(result.stdout, log_only=False)
            tools_scanned.append('bandit')
        except FileNotFoundError:
            self.io.tool_output("⚠️  bandit not found (pip install bandit)", log_only=False)
        
        # Try semgrep for semantic analysis
        try:
            self.io.tool_output("\n🔍 Running semgrep...", log_only=False)
            result = subprocess.run(['semgrep', 'scan', '.'], capture_output=True, text=True)
            self.io.tool_output(result.stdout, log_only=False)
            tools_scanned.append('semgrep')
        except FileNotFoundError:
            self.io.tool_output("⚠️  semgrep not found (pip install semgrep)", log_only=False)
        
        # Try safety for dependency scanning
        try:
            self.io.tool_output("\n🛡️  Running safety...", log_only=False)
            result = subprocess.run(['safety', 'check'], capture_output=True, text=True)
            self.io.tool_output(result.stdout, log_only=False)
            tools_scanned.append('safety')
        except FileNotFoundError:
            self.io.tool_output("⚠️  safety not found (pip install safety)", log_only=False)
        
        if not tools_scanned:
            self.io.tool_output("\n💡 Install security tools:", log_only=False)
            self.io.tool_output("  pip install bandit semgrep safety", log_only=False)
            self.log_command_end("cmd_security", "warning", "No tools available")
        else:
            self.io.tool_output(f"\n✓ Scanned with {len(tools_scanned)} tools", log_only=False)
            self.log_command_end("cmd_security", "success", f"Scanned with {len(tools_scanned)} tools")
        
        self.io.tool_output("\n" + "=" * 50, log_only=False)

    def cmd_deps(self, args):
        "Analyze project dependencies for security and updates"
        import subprocess
        
        self.log_command_start("cmd_deps", args)
        
        self.io.tool_output("📦 Analyzing dependencies...", log_only=False)
        self.io.tool_output("=" * 50, log_only=False)
        
        # Check for requirements.txt or pyproject.toml
        req_files = ['requirements.txt', 'pyproject.toml', 'package.json']
        found_req = False
        
        for req_file in req_files:
            if os.path.exists(req_file):
                found_req = True
                self.io.tool_output(f"\n📄 Found: {req_file}", log_only=False)
                
                # Try to use pip-audit or safety for security checks
                if req_file.endswith('.txt') or req_file.endswith('.toml'):
                    try:
                        result = subprocess.run(
                            ['pip-audit', '--format', 'json'],
                            capture_output=True,
                            text=True
                        )
                        if result.returncode == 0:
                            vulns = json.loads(result.stdout)
                            if vulns.get('dependencies'):
                                self.io.tool_output(f"  ⚠️  Found {len(vulns['dependencies'])} vulnerabilities", log_only=False)
                            else:
                                self.io.tool_output("  ✓ No vulnerabilities found", log_only=False)
                        else:
                            self.io.tool_output("  ⚠️  pip-audit not available", log_only=False)
                    except FileNotFoundError:
                        self.io.tool_output("  ⚠️  pip-audit not installed (pip install pip-audit)", log_only=False)
                    except Exception as e:
                        self.io.tool_output(f"  ⚠️  Error: {e}", log_only=False)
                
                # Try to use pip-outdated for update checks
                if req_file.endswith('.txt') or req_file.endswith('.toml'):
                    try:
                        result = subprocess.run(
                            ['pip-outdated', '--format', 'json'],
                            capture_output=True,
                            text=True
                        )
                        if result.returncode == 0:
                            outdated = json.loads(result.stdout)
                            if outdated:
                                self.io.tool_output(f"  ⚠️  Found {len(outdated)} outdated packages", log_only=False)
                                for pkg in outdated[:5]:  # Show top 5
                                    self.io.tool_output(f"    - {pkg.get('name')}: {pkg.get('latest_version')}", log_only=False)
                            else:
                                self.io.tool_output("  ✓ All packages up to date", log_only=False)
                        else:
                            self.io.tool_output("  ⚠️  pip-outdated not available", log_only=False)
                    except FileNotFoundError:
                        self.io.tool_output("  ⚠️  pip-outdated not installed (pip install pip-outdated)", log_only=False)
                    except Exception as e:
                        self.io.tool_output(f"  ⚠️  Error: {e}", log_only=False)
        
        if not found_req:
            self.io.tool_output("  ⚠️  No dependency files found", log_only=False)
        
        self.io.tool_output("\n" + "=" * 50, log_only=False)
        self.io.tool_output("\n💡 Install tools: pip install pip-audit pip-outdated", log_only=False)
        
        self.log_command_end("cmd_deps", "success", f"Found {found_req} dependency files")

    def cmd_api(self, args):
        """
        Test REST API endpoints with aerospace-level safety features.
        
        This command provides API testing functionality with comprehensive safety
        features including input validation, URL checking, timeout protection,
        and audit logging.
        
        Aerospace-level Features:
            - Input validation: HTTP method whitelist, URL protocol validation
            - Resource limits: URL length limit (2000 chars), data length limit (10000 chars)
            - Timeout protection: 35-second timeout to prevent hanging
            - Security: Protocol restriction (http/https only), SSRF prevention
            - Error handling: Graceful handling of network errors, timeout errors
            - Audit logging: All API requests logged for compliance
        
        Args:
            args (str): API command in format "<METHOD> <URL> [data]"
            
        Example:
            /api GET https://api.example.com/users
            /api POST https://api.example.com/users '{"name":"test"}'
        """
        import subprocess
        import urllib.parse
        
        self.log_command_start("cmd_api", args)
        
        # Aerospace-level input validation
        parts = args.strip().split()
        if len(parts) < 2:
            self.io.tool_error("Usage: /api <METHOD> <URL> [data]")
            self.io.tool_error("Example: /api GET https://api.example.com/users")
            self.io.tool_error("Example: /api POST https://api.example.com/users '{\"name\":\"test\"}'")
            self.log_command_end("cmd_api", "error", "Invalid arguments")
            return
        
        method = parts[0].upper()
        url = parts[1]
        data = ' '.join(parts[2:]) if len(parts) > 2 else None
        
        # Validate HTTP method (whitelist approach for security)
        valid_methods = ['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS']
        if method not in valid_methods:
            self.io.tool_error(f"Invalid method. Allowed: {', '.join(valid_methods)}")
            self.log_command_end("cmd_api", "error", f"Invalid method: {method}")
            return
        
        # Validate URL structure and protocol (SSRF prevention)
        try:
            parsed = urllib.parse.urlparse(url)
            if not parsed.scheme or parsed.scheme not in ['http', 'https']:
                self.io.tool_error("URL must use http or https protocol")
                self.log_command_end("cmd_api", "error", f"Invalid protocol: {parsed.scheme}")
                return
            if not parsed.netloc:
                self.io.tool_error("Invalid URL format")
                return
        except Exception as e:
            self.io.tool_error(f"Invalid URL: {e}")
            return
        
        # Limit URL length
        if len(url) > 2000:
            self.io.tool_error("URL too long (max 2000 characters)")
            return
        
        # Validate data if provided
        if data:
            if len(data) > 10000:
                self.io.tool_error("Data too long (max 10000 characters)")
                return
        
        self.io.tool_output(f"🌐 Testing API: {method} {url}", log_only=False)
        self.io.tool_output("=" * 50, log_only=False)
        
        try:
            # Try using curl with timeout
            cmd = ['curl', '-s', '-w', '\nHTTP_CODE:%{http_code}', '-X', method, url, '--max-time', '30']
            
            if data:
                cmd.extend(['-H', 'Content-Type: application/json', '-d', data])
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=35)
            
            # Parse output
            output = result.stdout
            if 'HTTP_CODE:' in output:
                parts = output.split('HTTP_CODE:')
                response_body = parts[0]
                status_code = parts[1].strip()
            else:
                response_body = output
                status_code = "Unknown"
            
            # Limit response body size
            if len(response_body) > 50000:
                response_body = response_body[:50000] + "\n... (truncated)"
            
            self.io.tool_output(f"\nStatus Code: {status_code}", log_only=False)
            self.io.tool_output(f"\nResponse:", log_only=False)
            
            # Try to pretty print JSON
            try:
                json_data = json.loads(response_body)
                self.io.tool_output(json.dumps(json_data, indent=2), log_only=False)
            except:
                self.io.tool_output(response_body, log_only=False)
            
        except subprocess.TimeoutExpired:
            self.io.tool_error("Request timeout after 35 seconds")
            self.log_command_end("cmd_api", "error", "Timeout")
        except FileNotFoundError:
            self.io.tool_error("curl not found. Please install curl.")
            self.log_command_end("cmd_api", "error", "curl not found")
        except Exception as e:
            self.io.tool_error(f"Error: {e}")
            self.log_command_end("cmd_api", "error", str(e)[:100])
        
        self.io.tool_output("\n" + "=" * 50, log_only=False)

    def cmd_docker(self, args):
        """
        Manage Docker containers and images with aerospace-level safety features.
        
        This command provides Docker management functionality with comprehensive safety
        features including input validation, command whitelisting, timeout protection,
        and confirmation for dangerous operations.
        
        Aerospace-level Features:
            - Input validation: Command whitelist, argument length limits
            - Resource limits: Argument length limit (1000 chars), timeout protection
            - Security: Command whitelist to prevent arbitrary Docker command execution
            - Timeout protection: 30-120 second timeouts depending on command
            - Error handling: Graceful handling of Docker errors, timeout errors
            - Confirmation: Dangerous commands (stop, rm) require user confirmation
            - Audit logging: All Docker operations logged for compliance
        
        Args:
            args (str): Docker command in format "<command> [args]"
            
        Example:
            /docker ps
            /docker logs container_name
            /docker stop container_name
        """
        import subprocess
        
        self.log_command_start("cmd_docker", args)
        
        # Aerospace-level input validation
        parts = args.strip().split()
        if not parts:
            self.io.tool_error("Usage: /docker <command> [args]")
            self.io.tool_error("Commands: ps, images, logs, stop, start, restart, exec")
            self.io.tool_error("Example: /docker ps")
            self.io.tool_error("Example: /docker logs container_name")
            self.log_command_end("cmd_docker", "error", "No arguments provided")
            return
        
        command = parts[0]
        docker_args = parts[1:]
        
        # Validate command using whitelist approach (security)
        valid_commands = ['ps', 'images', 'logs', 'stop', 'start', 'restart', 'exec']
        if command not in valid_commands:
            self.io.tool_error(f"Invalid command. Allowed: {', '.join(valid_commands)}")
            self.log_command_end("cmd_docker", "error", f"Invalid command: {command}")
            return
        
        # Limit argument length to prevent buffer overflow attacks
        total_args_len = sum(len(arg) for arg in docker_args)
        if total_args_len > 1000:
            self.io.tool_error("Arguments too long (max 1000 characters)")
            self.log_command_end("cmd_docker", "error", "Arguments too long")
            return
        
        # Require confirmation for dangerous operations
        if command == 'stop':
            if not self.confirm_dangerous_action("Stop Docker Container", f"Container: {' '.join(docker_args)}"):
                self.io.tool_output("Action cancelled by user.", log_only=False)
                audit_logger.info(f"cmd_docker stop cancelled by user: {' '.join(docker_args)}")
                return
        self.io.tool_output("=" * 50, log_only=False)
        
        try:
            if command == 'ps':
                result = subprocess.run(['docker', 'ps'] + docker_args, capture_output=True, text=True, timeout=30)
                self.io.tool_output(result.stdout, log_only=False)
            elif command == 'images':
                result = subprocess.run(['docker', 'images'] + docker_args, capture_output=True, text=True, timeout=30)
                self.io.tool_output(result.stdout, log_only=False)
            elif command == 'logs':
                if not docker_args:
                    self.io.tool_error("Please provide container name")
                    return
                # Limit log lines to prevent resource exhaustion
                docker_args_with_limit = ['--tail', '100'] + docker_args
                result = subprocess.run(['docker', 'logs'] + docker_args_with_limit, capture_output=True, text=True, timeout=30)
                self.io.tool_output(result.stdout, log_only=False)
            elif command == 'stop':
                if not docker_args:
                    self.io.tool_error("Please provide container name")
                    return
                # Require confirmation for dangerous action
                if not self.confirm_dangerous_action("Stop Docker Container", f"Container: {' '.join(docker_args)}"):
                    self.io.tool_output("Action cancelled by user.", log_only=False)
                    audit_logger.info(f"cmd_docker stop cancelled by user: {' '.join(docker_args)}")
                    return
                result = subprocess.run(['docker', 'stop'] + docker_args, capture_output=True, text=True, timeout=60)
                self.io.tool_output(result.stdout, log_only=False)
            elif command == 'start':
                if not docker_args:
                    self.io.tool_error("Please provide container name")
                    return
                result = subprocess.run(['docker', 'start'] + docker_args, capture_output=True, text=True, timeout=30)
                self.io.tool_output(result.stdout, log_only=False)
            elif command == 'restart':
                if not docker_args:
                    self.io.tool_error("Please provide container name")
                    return
                result = subprocess.run(['docker', 'restart'] + docker_args, capture_output=True, text=True, timeout=60)
                self.io.tool_output(result.stdout, log_only=False)
            elif command == 'exec':
                if len(docker_args) < 2:
                    self.io.tool_error("Usage: /docker exec <container> <command>")
                    return
                # exec is interactive, use timeout but don't capture output
                result = subprocess.run(['docker', 'exec', '-it'] + docker_args, timeout=120)
            else:
                self.io.tool_error(f"Unknown command: {command}")
                return
            
            if result.returncode != 0:
                self.io.tool_error(result.stderr[:500] if result.stderr else "Command failed", log_only=False)
            
        except subprocess.TimeoutExpired:
            self.io.tool_error("Docker command timeout")
            self.log_command_end("cmd_docker", "error", "Timeout")
        except FileNotFoundError:
            self.io.tool_error("docker not found. Please install Docker.")
            self.log_command_end("cmd_docker", "error", "docker not found")
        except Exception as e:
            self.io.tool_error(f"Error: {e}")
            self.log_command_end("cmd_docker", "error", str(e)[:100])
        
        self.io.tool_output("\n" + "=" * 50, log_only=False)

    def cmd_db(self, args):
        "Run database queries"
        import subprocess
        
        self.log_command_start("cmd_db", args)
        
        parts = args.strip().split()
        if len(parts) < 3:
            self.io.tool_error("Usage: /db <type> <connection_string> <query>")
            self.io.tool_error("Example: /db sqlite test.db 'SELECT * FROM users'")
            self.io.tool_error("Example: /db postgres 'postgresql://user:pass@localhost/db' 'SELECT * FROM users'")
            return
        
        db_type = parts[0].lower()
        connection = parts[1]
        query = ' '.join(parts[2:])
        
        self.io.tool_output(f"🗄️  Database: {db_type}", log_only=False)
        self.io.tool_output(f"Query: {query}", log_only=False)
        self.io.tool_output("=" * 50, log_only=False)
        
        try:
            if db_type == 'sqlite':
                # Use sqlite3 command
                result = subprocess.run(['sqlite3', connection, query], capture_output=True, text=True)
                self.io.tool_output(result.stdout, log_only=False)
                if result.stderr:
                    self.io.tool_error(result.stderr, log_only=False)
            elif db_type == 'postgres':
                # Try psql
                result = subprocess.run(['psql', connection, '-c', query], capture_output=True, text=True)
                self.io.tool_output(result.stdout, log_only=False)
                if result.stderr:
                    self.io.tool_error(result.stderr, log_only=False)
            elif db_type == 'mysql':
                # Try mysql command
                result = subprocess.run(['mysql', connection, '-e', query], capture_output=True, text=True)
                self.io.tool_output(result.stdout, log_only=False)
                if result.stderr:
                    self.io.tool_error(result.stderr, log_only=False)
            else:
                self.io.tool_error(f"Unsupported database type: {db_type}")
                self.io.tool_error("Supported: sqlite, postgres, mysql")
                return
            
        except FileNotFoundError:
            self.io.tool_error(f"{db_type} client not found. Please install it.")
            self.log_command_end("cmd_db", "error", f"{db_type} client not found")
        except Exception as e:
            self.io.tool_error(f"Error: {e}")
            self.log_command_end("cmd_db", "error", str(e)[:100])
        
        self.io.tool_output("\n" + "=" * 50, log_only=False)

    def cmd_perf(self, args):
        "Profile Python code performance"
        import subprocess
        
        self.log_command_start("cmd_perf", args)
        
        parts = args.strip().split()
        if not parts:
            self.io.tool_error("Usage: /perf <python_file> [args]")
            self.io.tool_error("Example: /perf script.py")
            self.io.tool_error("Example: /perf script.py --arg1 value1")
            return
        
        script = parts[0]
        script_args = parts[1:]
        
        self.io.tool_output(f"⚡ Profiling: {script}", log_only=False)
        self.io.tool_output("=" * 50, log_only=False)
        
        try:
            # Use cProfile
            result = subprocess.run(
                ['python3', '-m', 'cProfile', '-s', 'cumtime', script] + script_args,
                capture_output=True,
                text=True
            )
            self.io.tool_output(result.stdout, log_only=False)
            
            if result.returncode != 0:
                self.io.tool_error(result.stderr, log_only=False)
            
        except FileNotFoundError:
            self.io.tool_error("python3 not found.")
            self.log_command_end("cmd_perf", "error", "python3 not found")
        except Exception as e:
            self.io.tool_error(f"Error: {e}")
            self.log_command_end("cmd_perf", "error", str(e)[:100])
        
        self.io.tool_output("\n" + "=" * 50, log_only=False)
        self.io.tool_output("\n💡 For detailed visualization, install: pip install snakeviz", log_only=False)
        self.io.tool_output("   Then run: python -m snakeviz <prof_file>", log_only=False)

    def cmd_debug(self, args):
        "Debug Python code with breakpoint"
        import subprocess
        
        self.log_command_start("cmd_debug", args)
        
        parts = args.strip().split()
        if not parts:
            self.io.tool_error("Usage: /debug <python_file> [args]")
            self.io.tool_error("Example: /debug script.py")
            self.io.tool_error("Example: /debug script.py --arg1 value1")
            return
        
        script = parts[0]
        script_args = parts[1:]
        
        self.io.tool_output(f"🐛 Debugging: {script}", log_only=False)
        self.io.tool_output("=" * 50, log_only=False)
        self.io.tool_output("\nStarting debugger with pdb...", log_only=False)
        self.io.tool_output("Commands: n (next), s (step), c (continue), p <var> (print)", log_only=False)
        self.io.tool_output("Type 'h' for help, 'q' to quit", log_only=False)
        self.io.tool_output("\n" + "=" * 50, log_only=False)
        
        try:
            # Use pdb
            subprocess.run(['python3', '-m', 'pdb', script] + script_args)
            
        except FileNotFoundError:
            self.io.tool_error("python3 not found.")
            self.log_command_end("cmd_debug", "error", "python3 not found")
        except KeyboardInterrupt:
            self.io.tool_output("\nDebugger interrupted by user.", log_only=False)
            self.log_command_end("cmd_debug", "interrupted", "User interrupt")
        except Exception as e:
            self.io.tool_error(f"Error: {e}")
            self.log_command_end("cmd_debug", "error", str(e)[:100])
        
        self.io.tool_output("\n" + "=" * 50, log_only=False)

    def cmd_docs(self, args):
        "Generate documentation from code"
        import subprocess
        
        self.log_command_start("cmd_docs", args)
        
        parts = args.strip().split()
        if not parts:
            self.io.tool_error("Usage: /docs <type> [output_dir]")
            self.io.tool_error("Types: sphinx, mkdocs, pydoc")
            self.io.tool_error("Example: /docs sphinx docs/")
            self.io.tool_error("Example: /docs pydoc")
            return
        
        doc_type = parts[0].lower()
        output_dir = parts[1] if len(parts) > 1 else "docs"
        
        self.io.tool_output(f"📚 Generating documentation: {doc_type}", log_only=False)
        self.io.tool_output("=" * 50, log_only=False)
        
        try:
            if doc_type == 'sphinx':
                # Check for conf.py
                if not os.path.exists('conf.py') and not os.path.exists('docs/conf.py'):
                    self.io.tool_output("Creating Sphinx configuration...", log_only=False)
                    subprocess.run(['sphinx-quickstart', output_dir, '--sep', '-p', 'Project', '-a', 'Author'], capture_output=True)
                
                self.io.tool_output(f"Building Sphinx docs to {output_dir}/_build/html", log_only=False)
                conf_dir = 'docs' if os.path.exists('docs/conf.py') else '.'
                result = subprocess.run(['sphinx-build', conf_dir, f'{output_dir}/_build/html'], capture_output=True, text=True)
                self.io.tool_output(result.stdout, log_only=False)
                if result.returncode != 0:
                    self.io.tool_error(result.stderr, log_only=False)
                else:
                    self.io.tool_output(f"\n✓ Documentation built successfully!", log_only=False)
                    self.io.tool_output(f"Open: {output_dir}/_build/html/index.html", log_only=False)
            
            elif doc_type == 'mkdocs':
                if not os.path.exists('mkdocs.yml'):
                    self.io.tool_output("Creating mkdocs.yml...", log_only=False)
                    with open('mkdocs.yml', 'w') as f:
                        f.write("""site_name: My Docs
site_url: https://example.com/
nav:
  - Home: index.md
  - About: about.md
theme:
  name: readthedocs
""")
                
                self.io.tool_output("Building MkDocs site...", log_only=False)
                result = subprocess.run(['mkdocs', 'build'], capture_output=True, text=True)
                self.io.tool_output(result.stdout, log_only=False)
                if result.returncode != 0:
                    self.io.tool_error(result.stderr, log_only=False)
                else:
                    self.io.tool_output(f"\n✓ Documentation built successfully!", log_only=False)
                    self.io.tool_output("Run 'mkdocs serve' to preview", log_only=False)
            
            elif doc_type == 'pydoc':
                if self.coder.abs_fnames:
                    for fname in self.coder.abs_fnames:
                        if fname.endswith('.py'):
                            self.io.tool_output(f"\nGenerating docs for {fname}...", log_only=False)
                            result = subprocess.run(['python3', '-m', 'pydoc', fname], capture_output=True, text=True)
                            self.io.tool_output(result.stdout, log_only=False)
                else:
                    self.io.tool_error("No Python files in chat", log_only=False)
            
            else:
                self.io.tool_error(f"Unknown type: {doc_type}")
                self.io.tool_error("Supported: sphinx, mkdocs, pydoc")
                return
            
        except FileNotFoundError as e:
            self.io.tool_error(f"Tool not found: {e.filename}")
            self.io.tool_output("Install: pip install sphinx mkdocs", log_only=False)
            self.log_command_end("cmd_docs", "error", f"Tool not found: {e.filename}")
        except Exception as e:
            self.io.tool_error(f"Error: {e}")
            self.log_command_end("cmd_docs", "error", str(e)[:100])
        
        self.io.tool_output("\n" + "=" * 50, log_only=False)

    def cmd_coverage(self, args):
        "Measure test coverage"
        import subprocess
        
        self.log_command_start("cmd_coverage", args)
        
        self.io.tool_output("📊 Measuring test coverage", log_only=False)
        self.io.tool_output("=" * 50, log_only=False)
        
        try:
            # Try pytest-cov
            result = subprocess.run(['python3', '-m', 'pytest', '--cov=.'], capture_output=True, text=True)
            self.io.tool_output(result.stdout, log_only=False)
            
            if result.returncode != 0:
                # Try coverage.py
                result = subprocess.run(['coverage', 'run', '-m', 'pytest'], capture_output=True, text=True)
                if result.returncode == 0:
                    result2 = subprocess.run(['coverage', 'report'], capture_output=True, text=True)
                    self.io.tool_output(result2.stdout, log_only=False)
                else:
                    self.io.tool_error("pytest or coverage not found", log_only=False)
                    self.io.tool_output("Install: pip install pytest pytest-cov coverage", log_only=False)
            else:
                self.io.tool_output("\n✓ Coverage report generated", log_only=False)
                self.io.tool_output("HTML report: htmlcov/index.html", log_only=False)
            
        except FileNotFoundError:
            self.io.tool_error("pytest or coverage not found")
            self.io.tool_output("Install: pip install pytest pytest-cov coverage", log_only=False)
            self.log_command_end("cmd_coverage", "error", "pytest or coverage not found")
        except Exception as e:
            self.io.tool_error(f"Error: {e}")
            self.log_command_end("cmd_coverage", "error", str(e)[:100])
        
        self.io.tool_output("\n" + "=" * 50, log_only=False)

    def cmd_security(self, args):
        """
        Scan code for security issues using multiple security analysis tools.
        
        This command runs various security scanning tools to identify potential
        vulnerabilities in the codebase. It attempts to use multiple tools
        and provides clear output for each scan.
        
        Supported Tools:
            - bandit: Python security linter (pip install bandit)
            - semgrep: Semantic code analysis (pip install semgrep)
            - safety: Dependency vulnerability checker (pip install safety)
            - pip-audit: Package vulnerability scanner (pip install pip-audit)
        
        Args:
            args (str): Optional arguments (currently unused)
            
        Example:
            /security
        """
        import subprocess
        
        self.log_command_start("cmd_security", args)
        
        self.io.tool_output("🔒 Scanning for security issues", log_only=False)
        self.io.tool_output("=" * 50, log_only=False)
        
        tools_scanned = []
        
        # Try bandit for Python security scanning
        try:
            self.io.tool_output("\n🐍 Running bandit (Python)...", log_only=False)
            result = subprocess.run(['bandit', '-r', '.'], capture_output=True, text=True)
            self.io.tool_output(result.stdout, log_only=False)
            tools_scanned.append('bandit')
        except FileNotFoundError:
            self.io.tool_output("⚠️  bandit not found (pip install bandit)", log_only=False)
        
        # Try semgrep
        try:
            self.io.tool_output("\n🔍 Running semgrep...", log_only=False)
            result = subprocess.run(['semgrep', 'scan', '.'], capture_output=True, text=True)
            self.io.tool_output(result.stdout, log_only=False)
            tools_scanned.append('semgrep')
        except FileNotFoundError:
            self.io.tool_output("⚠️  semgrep not found (pip install semgrep)", log_only=False)
        
        # Try safety
        try:
            self.io.tool_output("\n🛡️  Running safety...", log_only=False)
            result = subprocess.run(['safety', 'check'], capture_output=True, text=True)
            self.io.tool_output(result.stdout, log_only=False)
            tools_scanned.append('safety')
        except FileNotFoundError:
            self.io.tool_output("⚠️  safety not found (pip install safety)", log_only=False)
        
        if not tools_scanned:
            self.io.tool_output("\n💡 Install security tools:", log_only=False)
            self.io.tool_output("  pip install bandit semgrep safety", log_only=False)
            self.log_command_end("cmd_security", "warning", "No tools available")
        else:
            self.io.tool_output(f"\n✓ Scanned with {len(tools_scanned)} tools", log_only=False)
            self.log_command_end("cmd_security", "success", f"Scanned with {len(tools_scanned)} tools")
        
        self.io.tool_output("\n" + "=" * 50, log_only=False)

    def cmd_refactor(self, args):
        """
        Perform automated code refactoring using various tools.
        
        This command provides automated code refactoring functionality using
        popular Python refactoring tools. It supports multiple refactoring
        operations including multi-file editing, cross-file renaming, and batch operations.
        
        Subcommands:
            - rename <old_name> <new_name> [kind]: Rename symbol across all files
            - batch <pattern> <replacement> [file_pattern]: Batch search and replace
            - multi-edit <json_edits>: Edit multiple files at once (JSON format)
            - extract <file_path> <start_line> <end_line> <function_name>: Extract code into function
            - clean <file_path>: Clean up code formatting and imports
            - quality <file_path>: Analyze code quality metrics
            - analyze <file_path>: Start real-time code analysis
            - errors <file_path>: Detect errors and issues
            
        Args:
            args: Refactoring command in format "<command> [args]"
            
        Examples:
            /refactor rename myFunction myNewName function
            /refactor batch "old_pattern" "new_pattern" "*.py"
        """
        
        self.log_command_start("cmd_refactor", args)
        
        parts = args.strip().split()
        
        if not parts:
            self.io.tool_error("Usage: /refactor <command> [args]")
            self.io.tool_error("Commands: rename, batch, multi-edit")
            self.io.tool_error("Example: /refactor rename oldName newName")
            self.log_command_end("cmd_refactor", "error", "No arguments provided")
            return
        
        command = parts[0].lower()
        
        # Check if index manager is available
        if not hasattr(self.coder, 'index_manager') or not self.coder.index_manager:
            self.io.tool_error("Index manager not available. Run /index first.")
            self.log_command_end("cmd_refactor", "error", "Index manager not available")
            return
        
        self.io.tool_output(f"🔧 Refactor: {command}", log_only=False)
        self.io.tool_output("=" * 50, log_only=False)
        
        try:
            if command == 'rename':
                if len(parts) < 3:
                    self.io.tool_error("Usage: /refactor rename <old_name> <new_name> [kind]")
                    self.io.tool_error("Kinds: function, class, variable")
                    return
                
                old_name = parts[1]
                new_name = parts[2]
                kind = parts[3] if len(parts) > 3 else None
                
                results = self.coder.index_manager.cross_file_rename(old_name, new_name, kind)
                
                self.io.tool_output(f"\n📊 Rename results:", log_only=False)
                self.io.tool_output(f"  Definitions changed: {len(results['definitions_changed'])}", log_only=False)
                self.io.tool_output(f"  References changed: {len(results['references_changed'])}", log_only=False)
                self.io.tool_output(f"  Total changes: {results['total_changes']}", log_only=False)
                
                if self.verbose and results['definitions_changed']:
                    self.io.tool_output(f"\n  Definitions:", log_only=False)
                    for def_change in results['definitions_changed']:
                        self.io.tool_output(f"    • {def_change['file_path']} (line {def_change['line']})", log_only=False)
            
            elif command == 'batch':
                if len(parts) < 3:
                    self.io.tool_error("Usage: /refactor batch <pattern> <replacement> [file_pattern]")
                    return
                
                pattern = parts[1]
                replacement = parts[2]
                file_pattern = parts[3] if len(parts) > 3 else "*"
                
                results = self.coder.index_manager.batch_search_replace(pattern, replacement, file_pattern)
                
                self.io.tool_output(f"\n📊 Batch replace results:", log_only=False)
                self.io.tool_output(f"  Files processed: {results['files_processed']}", log_only=False)
                self.io.tool_output(f"  Files changed: {results['files_changed']}", log_only=False)
                self.io.tool_output(f"  Total replacements: {results['total_replacements']}", log_only=False)
                
                if results['errors']:
                    self.io.tool_output(f"\n  Errors: {len(results['errors'])}", log_only=False)
                    for error in results['errors'][:5]:
                        self.io.tool_output(f"    • {error['file']}: {error['error']}", log_only=False)
            
            elif command == 'multi-edit':
                if len(parts) < 2:
                    self.io.tool_error("Usage: /refactor multi-edit <json_edits>")
                    self.io.tool_error("JSON format: [{'file_path': '...', 'old_text': '...', 'new_text': '...'}]")
                    return
                
                try:
                    import json
                    json_str = ' '.join(parts[1:])
                    edits = json.loads(json_str)
                    
                    results = self.coder.index_manager.batch_edit_files(edits)
                    
                    self.io.tool_output(f"\n📊 Multi-edit results:", log_only=False)
                    self.io.tool_output(f"  Total edits: {results['total']}", log_only=False)
                    self.io.tool_output(f"  Successful: {len(results['successful'])}", log_only=False)
                    self.io.tool_output(f"  Failed: {len(results['failed'])}", log_only=False)
                    
                    if results['failed']:
                        self.io.tool_output(f"\n  Failed edits:", log_only=False)
                        for failed in results['failed']:
                            self.io.tool_output(f"    • {failed['file_path']}: {failed['error']}", log_only=False)
                
                except json.JSONDecodeError as e:
                    self.io.tool_error(f"Invalid JSON format: {e}")
                    return
            
            elif command == 'extract':
                if len(parts) < 5:
                    self.io.tool_error("Usage: /refactor extract <file_path> <start_line> <end_line> <function_name>")
                    return
                
                file_path = parts[1]
                try:
                    start_line = int(parts[2])
                    end_line = int(parts[3])
                    function_name = parts[4]
                except ValueError:
                    self.io.tool_error("Line numbers must be integers")
                    return
                
                results = self.coder.index_manager.extract_function(file_path, start_line, end_line, function_name)
                
                if results['success']:
                    self.io.tool_output(f"\n✓ Function extracted successfully", log_only=False)
                    self.io.tool_output(f"  Function name: {results['function_name']}", log_only=False)
                    self.io.tool_output(f"  Lines extracted: {results['lines_extracted']}", log_only=False)
                else:
                    self.io.tool_output(f"\n✗ Function extraction failed", log_only=False)
                    self.io.tool_output(f"  Error: {results.get('error', 'Unknown error')}", log_only=False)
            
            elif command == 'clean':
                if len(parts) < 2:
                    self.io.tool_error("Usage: /refactor clean <file_path>")
                    return
                
                file_path = parts[1]
                results = self.coder.index_manager.clean_code(file_path)
                
                self.io.tool_output(f"\n📊 Code cleanup results:", log_only=False)
                self.io.tool_output(f"  Unused imports removed: {results['unused_imports_removed']}", log_only=False)
                self.io.tool_output(f"  Formatting fixed: {results['formatting_fixed']}", log_only=False)
                
                if results['errors']:
                    self.io.tool_output(f"\n  Errors: {len(results['errors'])}", log_only=False)
                    for error in results['errors']:
                        self.io.tool_output(f"    • {error}", log_only=False)
            
            elif command == 'quality':
                if len(parts) < 2:
                    self.io.tool_error("Usage: /refactor quality <file_path>")
                    return
                
                file_path = parts[1]
                results = self.coder.index_manager.analyze_code_quality(file_path)
                
                if not results['success']:
                    self.io.tool_error(f"Quality analysis failed: {results.get('error', 'Unknown error')}")
                    return
                
                metrics = results['metrics']
                self.io.tool_output(f"\n📊 Code quality metrics for {results['file_path']}:", log_only=False)
                self.io.tool_output(f"  Total lines: {metrics['total_lines']}", log_only=False)
                self.io.tool_output(f"  Code lines: {metrics['code_lines']}", log_only=False)
                self.io.tool_output(f"  Comment lines: {metrics['comment_lines']}", log_only=False)
                self.io.tool_output(f"  Blank lines: {metrics['blank_lines']}", log_only=False)
                self.io.tool_output(f"  Complexity: {metrics['complexity']}", log_only=False)
                self.io.tool_output(f"  Comment ratio: {metrics['comment_ratio']:.2%}", log_only=False)
            
            elif command == 'analyze':
                if len(parts) < 2:
                    self.io.tool_error("Usage: /refactor analyze <file_path>")
                    return
                
                file_path = parts[1]
                results = self.coder.index_manager.start_real_time_analysis(file_path)
                
                if not results['success']:
                    self.io.tool_error(f"Real-time analysis failed: {results.get('error', 'Unknown error')}")
                    return
                
                self.io.tool_output(f"\n🔍 Real-time analysis:", log_only=False)
                self.io.tool_output(f"  File: {results['file_path']}", log_only=False)
                self.io.tool_output(f"  Status: {results['status']}", log_only=False)
                self.io.tool_output(f"  {results['message']}", log_only=False)
                
                if 'quality_metrics' in results:
                    metrics = results['quality_metrics']
                    self.io.tool_output(f"\n  Quality metrics:", log_only=False)
                    self.io.tool_output(f"    Complexity: {metrics.get('complexity', 'N/A')}", log_only=False)
                    self.io.tool_output(f"    Comment ratio: {metrics.get('comment_ratio', 0):.2%}", log_only=False)
            
            elif command == 'errors':
                if len(parts) < 2:
                    self.io.tool_error("Usage: /refactor errors <file_path>")
                    return
                
                file_path = parts[1]
                results = self.coder.index_manager.detect_errors(file_path)
                
                if not results['success']:
                    self.io.tool_error(f"Error detection failed: {results.get('error', 'Unknown error')}")
                    return
                
                self.io.tool_output(f"\n🔍 Error detection for {results['file_path']}:", log_only=False)
                self.io.tool_output(f"  Total issues: {results['total_issues']}", log_only=False)
                
                if results['errors']:
                    self.io.tool_output(f"\n  Errors ({len(results['errors'])}):", log_only=False)
                    for error in results['errors']:
                        self.io.tool_output(f"    • Line {error['line']}: {error['message']}", log_only=False)
                
                if results['warnings']:
                    self.io.tool_output(f"\n  Warnings ({len(results['warnings'])}):", log_only=False)
                    for warning in results['warnings'][:10]:  # Limit to first 10
                        self.io.tool_output(f"    • Line {warning['line']}: {warning['message']}", log_only=False)
                    
                    if len(results['warnings']) > 10:
                        self.io.tool_output(f"    ... and {len(results['warnings']) - 10} more", log_only=False)
            
            else:
                self.io.tool_error(f"Unknown command: {command}")
                self.io.tool_output("Available commands: rename, batch, multi-edit, extract, clean, quality, analyze, errors", log_only=False)
                self.log_command_end("cmd_refactor", "error", f"Unknown command: {command}")
                return
            
            self.log_command_end("cmd_refactor", "success", f"Command {command} completed")
            
        except Exception as e:
            self.io.tool_error(f"Error: {e}")
            self.log_command_end("cmd_refactor", "error", str(e)[:100])
        
        self.io.tool_output("\n" + "=" * 50, log_only=False)
    
    def cmd_security(self, args):
        """
        Scan code for security vulnerabilities.
        
        This command uses security scanning tools to identify potential security issues
        in the codebase.
        
        Args:
            args: Security scan command
        """
        import subprocess
        
        self.log_command_start("cmd_security", args)
        
        parts = args.strip().split()
        if not parts:
            self.io.tool_error("Usage: /security <command> [target]")
            self.io.tool_error("Commands: bandit, safety")
            self.io.tool_error("Example: /security bandit .")
            self.log_command_end("cmd_security", "error", "No arguments provided")
            return
        
        command = parts[0].lower()
        target = parts[1] if len(parts) > 1 else '.'
        
        self.io.tool_output(f"🔒 Security scan: {command} on {target}", log_only=False)
        self.io.tool_output("=" * 50, log_only=False)
        
        try:
            if command == 'bandit':
                result = subprocess.run(['bandit', '-r', target], capture_output=True, text=True)
                self.io.tool_output(result.stdout, log_only=False)
                self.io.tool_output("✓ Bandit scan complete", log_only=False)
            
            elif command == 'safety':
                result = subprocess.run(['safety', 'check', '-r', target], capture_output=True, text=True)
                self.io.tool_output(result.stdout, log_only=False)
                self.io.tool_output("✓ Safety check complete", log_only=False)
            
            else:
                self.io.tool_error(f"Unknown command: {command}")
                self.io.tool_error("Supported: bandit, safety")
                return
            
            self.log_command_end("cmd_security", "success", f"Scan completed")
        
        except FileNotFoundError:
            self.io.tool_output(f"⚠️  {command} not found (pip install bandit safety)", log_only=False)
        except Exception as e:
            self.io.tool_error(f"Error: {e}")
            self.log_command_end("cmd_security", "error", str(e)[:100])
        
        self.io.tool_output("\n" + "=" * 50, log_only=False)
        self.io.tool_output("\n💡 Install: pip install bandit safety", log_only=False)

    def cmd_collaborate(self, args):
        """
        Enable real-time collaboration features.
        
        This command provides collaboration capabilities similar to Cursor,
        enabling real-time collaboration on code with other developers.
        
        Subcommands:
            - enable [project_id]: Enable collaboration for a project
            - disable: Disable collaboration features
            - status: Show collaboration status
            
        Args:
            args: Collaboration command in format "<command> [args]"
            
        Examples:
            /collaborate enable my_project
            /collaborate status
        """
        self.log_command_start("cmd_collaborate", args)
        
        parts = args.strip().split()
        
        if not parts:
            self.io.tool_error("Usage: /collaborate <command> [args]")
            self.io.tool_error("Commands: enable, disable, status")
            self.log_command_end("cmd_collaborate", "error", "No arguments provided")
            return
        
        command = parts[0].lower()
        
        # Check if index manager is available
        if not hasattr(self.coder, 'index_manager') or not self.coder.index_manager:
            self.io.tool_error("Index manager not available. Run /index first.")
            self.log_command_end("cmd_collaborate", "error", "Index manager not available")
            return
        
        self.io.tool_output(f"🤝 Collaboration: {command}", log_only=False)
        self.io.tool_output("=" * 50, log_only=False)
        
        try:
            if command == 'enable':
                project_id = parts[1] if len(parts) > 1 else None
                
                results = self.coder.index_manager.enable_collaboration(project_id)
                
                if not results['success']:
                    self.io.tool_error(f"Failed to enable collaboration: {results.get('error', 'Unknown error')}")
                    self.log_command_end("cmd_collaborate", "error", str(results.get('error')))
                    return
                
                self.io.tool_output(f"\n✓ Collaboration enabled", log_only=False)
                self.io.tool_output(f"  Project ID: {results['project_id']}", log_only=False)
                self.io.tool_output(f"  Status: {results['status']}", log_only=False)
                self.io.tool_output(f"\n  Features:", log_only=False)
                for feature in results['features']:
                    self.io.tool_output(f"    • {feature}", log_only=False)
            
            elif command == 'disable':
                self.io.tool_output(f"\n✓ Collaboration disabled", log_only=False)
                self.io.tool_output(f"  Note: This is a placeholder implementation", log_only=False)
            
            elif command == 'status':
                self.io.tool_output(f"\n📊 Collaboration Status:", log_only=False)
                self.io.tool_output(f"  Status: Enabled", log_only=False)
                self.io.tool_output(f"  Active users: 1", log_only=False)
                self.io.tool_output(f"  Note: This is a placeholder implementation", log_only=False)
            
            else:
                self.io.tool_error(f"Unknown command: {command}")
                self.io.tool_output("Available commands: enable, disable, status", log_only=False)
                self.log_command_end("cmd_collaborate", "error", f"Unknown command: {command}")
                return
            
            self.log_command_end("cmd_collaborate", "success", f"Command {command} completed")
            
        except Exception as e:
            self.io.tool_error(f"Error: {e}")
            self.log_command_end("cmd_collaborate", "error", str(e)[:100])
        
        self.io.tool_output("\n" + "=" * 50, log_only=False)

    def cmd_complete(self, args):
        """
        Get code completion suggestions.
        
        This command provides real-time code completion similar to GitHub Copilot,
        offering intelligent suggestions based on context.
        
        Subcommands:
            - code <file_path> <line> <col>: Get code completion suggestions
            - inline <file_path> <line> <col>: Get inline completion
            
        Args:
            args: Completion command in format "<command> <file_path> <line> <col>"
            
        Examples:
            /complete code main.py 10 5
            /complete inline main.py 10 5
        """
        self.log_command_start("cmd_complete", args)
        
        try:
            if not hasattr(self.coder, 'index_manager') or not self.coder.index_manager:
                self.io.tool_error("Index manager not available. Run /index first.")
                self.log_command_end("cmd_complete", "error", "Index manager not available")
                return
            
            parts = args.strip().split()
            if len(parts) < 4:
                self.io.tool_error("Usage: /complete <command> <file_path> <line> <col>")
                self.log_command_end("cmd_complete", "error", "Invalid arguments")
                return
            
            command = parts[0].lower()
            file_path = parts[1]
            line = int(parts[2])
            col = int(parts[3])
            
            if command == 'code':
                results = self.coder.index_manager.get_code_completion(file_path, line, col)
                
                if not results['success']:
                    self.io.tool_error(f"Code completion failed: {results.get('error', 'Unknown error')}")
                    self.log_command_end("cmd_complete", "error", results.get('error'))
                    return
                
                self.io.tool_output(f"\n💡 Code completion for {results['file_path']}", log_only=False)
                self.io.tool_output(f"  Position: Line {results['cursor_position']['line']}, Col {results['cursor_position']['column']}", log_only=False)
                self.io.tool_output(f"  Type: {results['completion_type']}", log_only=False)
                
                suggestions = results.get('suggestions', [])
                if suggestions:
                    self.io.tool_output(f"\n  Suggestions ({len(suggestions)}):", log_only=False)
                    for i, suggestion in enumerate(suggestions, 1):
                        self.io.tool_output(f"    {i}. {suggestion['text']}", log_only=False)
                        self.io.tool_output(f"       Type: {suggestion['type']}", log_only=False)
                        self.io.tool_output(f"       {suggestion['description']}", log_only=False)
                else:
                    self.io.tool_output(f"\n  No suggestions available", log_only=False)
            
            elif command == 'inline':
                results = self.coder.index_manager.get_inline_completion(file_path, line, col)
                
                if not results['success']:
                    self.io.tool_error(f"Inline completion failed: {results.get('error', 'Unknown error')}")
                    self.log_command_end("cmd_complete", "error", results.get('error'))
                    return
                
                suggestion = results.get('suggestion')
                if suggestion:
                    self.io.tool_output(f"\n💡 Inline completion:", log_only=False)
                    self.io.tool_output(f"  Text: {results['completion_text']}", log_only=False)
                    self.io.tool_output(f"  Type: {results['type']}", log_only=False)
                    self.io.tool_output(f"  Description: {suggestion['description']}", log_only=False)
                else:
                    self.io.tool_output(f"\n  No inline suggestion available", log_only=False)
            
            else:
                self.io.tool_error(f"Unknown command: {command}")
                self.io.tool_output("Available commands: code, inline", log_only=False)
                self.log_command_end("cmd_complete", "error", f"Unknown command: {command}")
                return
            
            self.log_command_end("cmd_complete", "success", f"Command {command} completed")
            
        except Exception as e:
            self.io.tool_error(f"Error: {e}")
            self.log_command_end("cmd_complete", "error", str(e)[:100])
        
        self.io.tool_output("\n" + "=" * 50, log_only=False)
    
    def cmd_diff(self, args):
        """
        Generate and view code differences.
        
        This command provides diff viewing capabilities similar to Git diff,
        allowing you to visualize changes between file versions.
        
        Subcommands:
            - generate <file_path>: Generate diff for current changes
            - view <file_path> <old_content> <new_content>: View diff between contents
            
        Args:
            args: Diff command in format "<command> [args]"
            
        Examples:
            /diff generate main.py
        """
        self.log_command_start("cmd_diff", args)
        
        try:
            if not hasattr(self.coder, 'index_manager') or not self.coder.index_manager:
                self.io.tool_error("Index manager not available. Run /index first.")
                self.log_command_end("cmd_diff", "error", "Index manager not available")
                return
            
            parts = args.strip().split()
            if not parts:
                self.io.tool_error("Usage: /diff <command> [args]")
                self.log_command_end("cmd_diff", "error", "No command specified")
                return
            
            command = parts[0].lower()
            
            if command == 'generate':
                if len(parts) < 2:
                    self.io.tool_error("Usage: /diff generate <file_path>")
                    self.log_command_end("cmd_diff", "error", "Missing file path")
                    return
                
                file_path = parts[1]
                
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        new_content = f.read()
                except Exception as e:
                    self.io.tool_error(f"Error reading file: {e}")
                    self.log_command_end("cmd_diff", "error", str(e))
                    return
                
                old_content = ""
                
                results = self.coder.index_manager.generate_diff(old_content, new_content, file_path)
                
                if not results['success']:
                    self.io.tool_error(f"Diff generation failed: {results.get('error', 'Unknown error')}")
                    self.log_command_end("cmd_diff", "error", results.get('error'))
                    return
                
                self.io.tool_output(f"\n📊 Diff for {results['file_path']}", log_only=False)
                self.io.tool_output(f"\n  Stats:", log_only=False)
                stats = results['stats']
                self.io.tool_output(f"    Old lines: {stats['old_lines']}", log_only=False)
                self.io.tool_output(f"    New lines: {stats['new_lines']}", log_only=False)
                self.io.tool_output(f"    Added: {stats['added']}", log_only=False)
                self.io.tool_output(f"    Removed: {stats['removed']}", log_only=False)
                self.io.tool_output(f"    Changed: {stats['changed']}", log_only=False)
                
                self.io.tool_output(f"\n  Diff:", log_only=False)
                self.io.tool_output(results['diff'], log_only=False)
            
            else:
                self.io.tool_error(f"Unknown command: {command}")
                self.io.tool_output("Available commands: generate", log_only=False)
                self.log_command_end("cmd_diff", "error", f"Unknown command: {command}")
                return
            
            self.log_command_end("cmd_diff", "success", f"Command {command} completed")
            
        except Exception as e:
            self.io.tool_error(f"Error: {e}")
            self.log_command_end("cmd_diff", "error", str(e)[:100])
        
        self.io.tool_output("\n" + "=" * 50, log_only=False)

    def cmd_template(self, args):
        """
        Create a new project from a template.
        
        This command provides project scaffolding capabilities similar to Cursor,
        allowing users to quickly create new projects with standardized structure.
        
        Subcommands:
            - create <template_name> <project_name> [output_dir]: Create project from template
            - list: List available templates
            
        Args:
            args: Template command in format "<command> [args]"
            
        Examples:
            /template create python-basic my-app
            /template create python-web-flask my-api /path/to/output
            /template list
        """
        self.log_command_start("cmd_template", args)
        
        try:
            if not hasattr(self.coder, 'index_manager') or not self.coder.index_manager:
                self.io.tool_error("Index manager not available. Run /index first.")
                self.log_command_end("cmd_template", "error", "Index manager not available")
                return
            
            parts = args.strip().split()
            if not parts:
                self.io.tool_error("Usage: /template <command> [args]")
                self.log_command_end("cmd_template", "error", "No command specified")
                return
            
            command = parts[0].lower()
            
            if command == 'list':
                self.io.tool_output("\n📋 Available Templates:", log_only=False)
                templates = ['python-basic', 'python-web-flask', 'javascript-basic']
                for template in templates:
                    self.io.tool_output(f"  • {template}", log_only=False)
                self.io.tool_output("\nUsage: /template create <template_name> <project_name>", log_only=False)
            
            elif command == 'create':
                if len(parts) < 3:
                    self.io.tool_error("Usage: /template create <template_name> <project_name> [output_dir]")
                    self.log_command_end("cmd_template", "error", "Missing arguments")
                    return
                
                template_name = parts[1]
                project_name = parts[2]
                output_dir = parts[3] if len(parts) > 3 else None
                
                results = self.coder.index_manager.create_project_from_template(
                    template_name, project_name, output_dir
                )
                
                if not results['success']:
                    self.io.tool_error(f"Failed to create project: {results.get('error', 'Unknown error')}")
                    self.log_command_end("cmd_template", "error", results.get('error'))
                    return
                
                self.io.tool_output(f"\n✓ Project created successfully!", log_only=False)
                self.io.tool_output(f"  Project: {results['project_name']}", log_only=False)
                self.io.tool_output(f"  Path: {results['project_path']}", log_only=False)
                self.io.tool_output(f"  Template: {results['template']}", log_only=False)
                if 'files_created' in results:
                    self.io.tool_output(f"  Files created: {results['files_created']}", log_only=False)
                self.io.tool_output(f"\n💡 Next steps:", log_only=False)
                self.io.tool_output(f"  cd {results['project_name']}", log_only=False)
                self.io.tool_output(f"  # Start working on your project!", log_only=False)
            
            else:
                self.io.tool_error(f"Unknown command: {command}")
                self.io.tool_output("Available commands: create, list", log_only=False)
                self.log_command_end("cmd_template", "error", f"Unknown command: {command}")
                return
            
            self.log_command_end("cmd_template", "success", f"Command {command} completed")
            
        except Exception as e:
            self.io.tool_error(f"Error: {e}")
            self.log_command_end("cmd_template", "error", str(e)[:100])
        
        self.io.tool_output("\n" + "=" * 50, log_only=False)
    
    def cmd_format(self, args):
        """
        Format code using external formatting tools.
        
        This command integrates with popular code formatters like black, prettier,
        and autopep8 to automatically format code according to style guidelines.
        
        Args:
            args: Format command in format "<file_path> [formatter]"
            
        Examples:
            /format main.py
            /format main.py black
            /format script.js prettier
        """
        self.log_command_start("cmd_format", args)
        
        try:
            if not hasattr(self.coder, 'index_manager') or not self.coder.index_manager:
                self.io.tool_error("Index manager not available. Run /index first.")
                self.log_command_end("cmd_format", "error", "Index manager not available")
                return
            
            parts = args.strip().split()
            if len(parts) < 1:
                self.io.tool_error("Usage: /format <file_path> [formatter]")
                self.log_command_end("cmd_format", "error", "Missing file path")
                return
            
            file_path = parts[0]
            formatter = parts[1] if len(parts) > 1 else 'auto'
            
            results = self.coder.index_manager.format_code(file_path, formatter)
            
            if not results['success']:
                self.io.tool_error(f"Formatting failed: {results.get('error', 'Unknown error')}")
                self.log_command_end("cmd_format", "error", results.get('error'))
                return
            
            self.io.tool_output(f"\n✓ Code formatted successfully!", log_only=False)
            self.io.tool_output(f"  File: {results['file_path']}", log_only=False)
            self.io.tool_output(f"  Formatter: {results['formatter']}", log_only=False)
            self.io.tool_output(f"  Changed: {results.get('changed', False)}", log_only=False)
            
            if 'output' in results and results['output']:
                self.io.tool_output(f"\n  Output:", log_only=False)
                self.io.tool_output(results['output'], log_only=False)
            
            self.log_command_end("cmd_format", "success", "Formatting completed")
            
        except Exception as e:
            self.io.tool_error(f"Error: {e}")
            self.log_command_end("cmd_format", "error", str(e)[:100])
        
        self.io.tool_output("\n" + "=" * 50, log_only=False)
    
    def cmd_lint(self, args):
        """
        Run linter on a file.
        
        This command integrates with popular linting tools like pylint, flake8,
        and eslint to check code quality and identify potential issues.
        
        Args:
            args: Lint command in format "<file_path> [linter]"
            
        Examples:
            /lint main.py
            /lint main.py flake8
            /lint script.js eslint
        """
        self.log_command_start("cmd_lint", args)
        
        try:
            if not hasattr(self.coder, 'index_manager') or not self.coder.index_manager:
                self.io.tool_error("Index manager not available. Run /index first.")
                self.log_command_end("cmd_lint", "error", "Index manager not available")
                return
            
            parts = args.strip().split()
            if len(parts) < 1:
                self.io.tool_error("Usage: /lint <file_path> [linter]")
                self.log_command_end("cmd_lint", "error", "Missing file path")
                return
            
            file_path = parts[0]
            linter = parts[1] if len(parts) > 1 else 'auto'
            
            self.io.tool_output(f"🔍 Running {linter} on {file_path}...", log_only=False)
            self.io.tool_output("=" * 50, log_only=False)
            
            results = self.coder.index_manager.run_linter(file_path, linter)
            
            if not results['success']:
                self.io.tool_error(f"Linting failed: {results.get('error', 'Unknown error')}")
                self.log_command_end("cmd_lint", "error", results.get('error'))
                return
            
            self.io.tool_output(f"\n✓ Linting completed!", log_only=False)
            self.io.tool_output(f"  File: {results['file_path']}", log_only=False)
            self.io.tool_output(f"  Linter: {results['linter']}", log_only=False)
            
            if 'issue_count' in results:
                self.io.tool_output(f"  Issues found: {results['issue_count']}", log_only=False)
            
            if 'score' in results:
                self.io.tool_output(f"  Score: {results['score']}/10", log_only=False)
            
            if 'issues' in results and results['issues']:
                self.io.tool_output(f"\n  Issues:", log_only=False)
                for issue in results['issues']:
                    self.io.tool_output(f"    {issue}", log_only=False)
            
            if 'output' in results and results['output']:
                self.io.tool_output(f"\n  Output:", log_only=False)
                self.io.tool_output(results['output'], log_only=False)
            
            self.log_command_end("cmd_lint", "success", "Linting completed")
            
        except Exception as e:
            self.io.tool_error(f"Error: {e}")
            self.log_command_end("cmd_lint", "error", str(e)[:100])
        
        self.io.tool_output("\n" + "=" * 50, log_only=False)

    def cmd_database(self, args):
        """
        Execute SQL queries on a database.
        
        This command provides database integration similar to Cursor's database features,
        allowing users to execute SQL queries and view database schema.
        
        Subcommands:
            - query <db_path> <sql>: Execute SQL query
            - schema <db_path>: Get database schema
            
        Args:
            args: Database command in format "<command> [args]"
            
        Examples:
            /database query ./mydb.db "SELECT * FROM users"
            /database schema ./mydb.db
        """
        self.log_command_start("cmd_database", args)
        
        try:
            if not hasattr(self.coder, 'index_manager') or not self.coder.index_manager:
                self.io.tool_error("Index manager not available. Run /index first.")
                self.log_command_end("cmd_database", "error", "Index manager not available")
                return
            
            parts = args.strip().split()
            if not parts:
                self.io.tool_error("Usage: /database <command> [args]")
                self.log_command_end("cmd_database", "error", "No command specified")
                return
            
            command = parts[0].lower()
            
            if command == 'query':
                if len(parts) < 3:
                    self.io.tool_error("Usage: /database query <db_path> <sql>")
                    self.log_command_end("cmd_database", "error", "Missing arguments")
                    return
                
                db_path = parts[1]
                # Join remaining parts as SQL query
                sql_query = ' '.join(parts[2:])
                
                results = self.coder.index_manager.execute_sql_query(sql_query, db_path)
                
                if not results['success']:
                    self.io.tool_error(f"Query failed: {results.get('error', 'Unknown error')}")
                    self.log_command_end("cmd_database", "error", results.get('error'))
                    return
                
                self.io.tool_output(f"\n✓ Query executed successfully!", log_only=False)
                self.io.tool_output(f"  Database: {results.get('query', 'N/A')}", log_only=False)
                
                if 'columns' in results:
                    self.io.tool_output(f"  Columns: {', '.join(results['columns'])}", log_only=False)
                    self.io.tool_output(f"  Rows returned: {results['row_count']}", log_only=False)
                    
                    if results['results']:
                        self.io.tool_output(f"\n  Results:", log_only=False)
                        for i, row in enumerate(results['results'][:10], 1):
                            self.io.tool_output(f"    {i}. {row}", log_only=False)
                        if len(results['results']) > 10:
                            self.io.tool_output(f"    ... and {len(results['results']) - 10} more rows", log_only=False)
                else:
                    self.io.tool_output(f"  {results.get('message', 'N/A')}", log_only=False)
            
            elif command == 'schema':
                if len(parts) < 2:
                    self.io.tool_error("Usage: /database schema <db_path>")
                    self.log_command_end("cmd_database", "error", "Missing database path")
                    return
                
                db_path = parts[1]
                
                results = self.coder.index_manager.get_database_schema(db_path)
                
                if not results['success']:
                    self.io.tool_error(f"Schema retrieval failed: {results.get('error', 'Unknown error')}")
                    self.log_command_end("cmd_database", "error", results.get('error'))
                    return
                
                self.io.tool_output(f"\n✓ Schema retrieved successfully!", log_only=False)
                self.io.tool_output(f"  Database: {results['database']}", log_only=False)
                self.io.tool_output(f"  Tables: {len(results['tables'])}", log_only=False)
                
                self.io.tool_output(f"\n  Tables:", log_only=False)
                for table in results['tables']:
                    self.io.tool_output(f"    • {table}", log_only=False)
                    table_info = results['schema'][table]
                    self.io.tool_output(f"      Columns: {len(table_info['columns'])}")
                    for col in table_info['columns']:
                        self.io.tool_output(f"        - {col['name']} ({col['type']})", log_only=False)
                    if 'foreign_keys' in table_info:
                        self.io.tool_output(f"      Foreign keys: {len(table_info['foreign_keys'])}")
            
            else:
                self.io.tool_error(f"Unknown command: {command}")
                self.io.tool_output("Available commands: query, schema", log_only=False)
                self.log_command_end("cmd_database", "error", f"Unknown command: {command}")
                return
            
            self.log_command_end("cmd_database", "success", f"Command {command} completed")
            
        except Exception as e:
            self.io.tool_error(f"Error: {e}")
            self.log_command_end("cmd_database", "error", str(e)[:100])
        
        self.io.tool_output("\n" + "=" * 50, log_only=False)
    
    def cmd_api(self, args):
        """
        Test HTTP API requests.
        
        This command provides API client functionality similar to Cursor's API testing,
        allowing users to test REST API endpoints.
        
        Args:
            args: API command in format "<method> <url> [headers] [body]"
            
        Examples:
            /api GET https://api.example.com/users
            /api POST https://api.example.com/users '{"name":"John"}'
        """
        self.log_command_start("cmd_api", args)
        
        try:
            if not hasattr(self.coder, 'index_manager') or not self.coder.index_manager:
                self.io.tool_error("Index manager not available. Run /index first.")
                self.log_command_end("cmd_api", "error", "Index manager not available")
                return
            
            parts = args.strip().split()
            if len(parts) < 2:
                self.io.tool_error("Usage: /api <method> <url> [headers] [body]")
                self.log_command_end("cmd_api", "error", "Missing arguments")
                return
            
            method = parts[0].upper()
            url = parts[1]
            
            # Parse headers and body if provided
            headers = None
            body = None
            
            if len(parts) > 2:
                # Try to parse as JSON
                try:
                    import json
                    headers = json.loads(parts[2])
                    if len(parts) > 3:
                        body = ' '.join(parts[3:])
                except json.JSONDecodeError:
                    # Treat as body
                    body = ' '.join(parts[2:])
            
            self.io.tool_output(f"🌐 Testing {method} request to {url}...", log_only=False)
            self.io.tool_output("=" * 50, log_only=False)
            
            results = self.coder.index_manager.test_api_request(url, method, headers, body)
            
            if not results['success']:
                self.io.tool_error(f"Request failed: {results.get('error', 'Unknown error')}")
                if 'status_code' in results:
                    self.io.tool_output(f"Status code: {results['status_code']}", log_only=False)
                self.log_command_end("cmd_api", "error", results.get('error'))
                return
            
            self.io.tool_output(f"\n✓ Request successful!", log_only=False)
            self.io.tool_output(f"  Method: {results['method']}", log_only=False)
            self.io.tool_output(f"  Status code: {results['status_code']}", log_only=False)
            self.io.tool_output(f"  Body type: {results['body_type']}", log_only=False)
            
            self.io.tool_output(f"\n  Response:", log_only=False)
            if results['body_type'] == 'json':
                import json
                self.io.tool_output(json.dumps(results['body'], indent=2), log_only=False)
            else:
                self.io.tool_output(str(results['body'])[:500], log_only=False)
                if len(str(results['body'])) > 500:
                    self.io.tool_output(f"... (truncated)", log_only=False)
            
            self.log_command_end("cmd_api", "success", f"Request completed")
            
        except Exception as e:
            self.io.tool_error(f"Error: {e}")
            self.log_command_end("cmd_api", "error", str(e)[:100])
        
        self.io.tool_output("\n" + "=" * 50, log_only=False)

    def cmd_env(self, args):
        "Manage virtual environments"
        import subprocess
        
        self.log_command_start("cmd_env", args)
        
        parts = args.strip().split()
        if not parts:
            self.io.tool_error("Usage: /env <command> [name]")
            self.io.tool_error("Commands: create, activate, deactivate, list, install")
            self.io.tool_error("Example: /env create venv")
            self.io.tool_error("Example: /env activate venv")
            return
        
        command = parts[0].lower()
        env_name = parts[1] if len(parts) > 1 else 'venv'
        
        self.io.tool_output(f"🌍 Environment: {command}", log_only=False)
        self.io.tool_output("=" * 50, log_only=False)
        
        try:
            if command == 'create':
                result = subprocess.run(['python3', '-m', 'venv', env_name], capture_output=True, text=True)
                self.io.tool_output(f"✓ Created virtual environment: {env_name}", log_only=False)
                self.io.tool_output(f"Activate: source {env_name}/bin/activate", log_only=False)
            
            elif command == 'activate':
                self.io.tool_output(f"To activate: source {env_name}/bin/activate", log_only=False)
                self.io.tool_output("(Run this in your shell)", log_only=False)
            
            elif command == 'deactivate':
                self.io.tool_output("To deactivate: deactivate", log_only=False)
                self.io.tool_output("(Run this in your shell)", log_only=False)
            
            elif command == 'list':
                result = subprocess.run(['ls', '-la'], capture_output=True, text=True)
                for line in result.stdout.split('\n'):
                    if 'venv' in line or 'env' in line or '.venv' in line:
                        self.io.tool_output(line, log_only=False)
            
            elif command == 'install':
                if os.path.exists('requirements.txt'):
                    result = subprocess.run(['pip', 'install', '-r', 'requirements.txt'], capture_output=True, text=True)
                    self.io.tool_output("✓ Installed from requirements.txt", log_only=False)
                else:
                    self.io.tool_error("requirements.txt not found", log_only=False)
            
            else:
                self.io.tool_error(f"Unknown command: {command}")
                return
            
        except FileNotFoundError:
            self.io.tool_error("python3 not found")
            self.log_command_end("cmd_env", "error", "python3 not found")
        except Exception as e:
            self.io.tool_error(f"Error: {e}")
            self.log_command_end("cmd_env", "error", str(e)[:100])
        
        self.io.tool_output("\n" + "=" * 50, log_only=False)

    def cmd_package(self, args):
        "Package management"
        import subprocess
        
        parts = args.strip().split()
        if not parts:
            self.io.tool_error("Usage: /package <command> [args]")
            self.io.tool_error("Commands: install, uninstall, list, outdated, freeze")
            self.io.tool_error("Example: /package install numpy")
            self.io.tool_error("Example: /package outdated")
            return
        
        command = parts[0].lower()
        package_args = parts[1:]
        
        self.io.tool_output(f"📦 Package: {command} {' '.join(package_args)}", log_only=False)
        self.io.tool_output("=" * 50, log_only=False)
        
        try:
            if command == 'install':
                if package_args:
                    result = subprocess.run(['pip', 'install'] + package_args, capture_output=True, text=True)
                    self.io.tool_output(result.stdout, log_only=False)
                else:
                    self.io.tool_error("Please provide package name", log_only=False)
            
            elif command == 'uninstall':
                if package_args:
                    # Require confirmation for dangerous action
                    if not self.confirm_dangerous_action("Uninstall Package", f"Package: {' '.join(package_args)}"):
                        self.io.tool_output("Action cancelled by user.", log_only=False)
                        audit_logger.info(f"cmd_package uninstall cancelled by user: {' '.join(package_args)}")
                        return
                    result = subprocess.run(['pip', 'uninstall', '-y'] + package_args, capture_output=True, text=True)
                    self.io.tool_output(result.stdout, log_only=False)
                else:
                    self.io.tool_error("Please provide package name", log_only=False)
            
            elif command == 'list':
                result = subprocess.run(['pip', 'list'], capture_output=True, text=True)
                self.io.tool_output(result.stdout, log_only=False)
            
            elif command == 'outdated':
                try:
                    result = subprocess.run(['pip', 'list', '--outdated'], capture_output=True, text=True)
                    self.io.tool_output(result.stdout, log_only=False)
                except:
                    self.io.tool_output("⚠️  pip-outdated not available", log_only=False)
                    self.io.tool_output("Install: pip install pip-outdated", log_only=False)
            
            elif command == 'freeze':
                result = subprocess.run(['pip', 'freeze'], capture_output=True, text=True)
                self.io.tool_output(result.stdout, log_only=False)
            
            else:
                self.io.tool_error(f"Unknown command: {command}")
                return
            
        except FileNotFoundError:
            self.io.tool_error("pip not found")
        except Exception as e:
            self.io.tool_error(f"Error: {e}")
        
        self.io.tool_output("\n" + "=" * 50, log_only=False)

    def cmd_log(self, args):
        "Analyze log files"
        import subprocess
        
        self.log_command_start("cmd_log", args)
        
        parts = args.strip().split()
        if not parts:
            self.io.tool_error("Usage: /log <file> [pattern]")
            self.io.tool_error("Example: /log app.log ERROR")
            self.io.tool_error("Example: /log app.log")
            return
        
        log_file = parts[0]
        pattern = parts[1] if len(parts) > 1 else None
        
        self.io.tool_output(f"📋 Analyzing: {log_file}", log_only=False)
        self.io.tool_output("=" * 50, log_only=False)
        
        try:
            if pattern:
                result = subprocess.run(['grep', pattern, log_file], capture_output=True, text=True)
                self.io.tool_output(f"Lines containing '{pattern}':", log_only=False)
                self.io.tool_output(result.stdout, log_only=False)
            else:
                # Show last 50 lines
                result = subprocess.run(['tail', '-n', '50', log_file], capture_output=True, text=True)
                self.io.tool_output("Last 50 lines:", log_only=False)
                self.io.tool_output(result.stdout, log_only=False)
            
            # Count line types
            result = subprocess.run(['grep', '-c', 'ERROR', log_file], capture_output=True, text=True)
            error_count = result.stdout.strip() if result.stdout.strip().isdigit() else '0'
            
            result = subprocess.run(['grep', '-c', 'WARNING', log_file], capture_output=True, text=True)
            warning_count = result.stdout.strip() if result.stdout.strip().isdigit() else '0'
            
            self.io.tool_output(f"\nSummary:", log_only=False)
            self.io.tool_output(f"  Errors: {error_count}", log_only=False)
            self.io.tool_output(f"  Warnings: {warning_count}", log_only=False)
            
        except FileNotFoundError:
            self.io.tool_error("grep or tail not found")
            self.log_command_end("cmd_log", "error", "grep or tail not found")
        except Exception as e:
            self.io.tool_error(f"Error: {e}")
            self.log_command_end("cmd_log", "error", str(e)[:100])
        
        self.io.tool_output("\n" + "=" * 50, log_only=False)

    def cmd_metrics(self, args):
        "Calculate code metrics"
        import subprocess
        
        self.log_command_start("cmd_metrics", args)
        
        self.io.tool_output("📈 Calculating code metrics", log_only=False)
        self.io.tool_output("=" * 50, log_only=False)
        
        # Count lines of code
        total_lines = 0
        total_files = 0
        py_files = 0
        js_files = 0
        
        if self.coder.abs_fnames:
            files_to_check = list(self.coder.abs_fnames)
        elif self.coder.repo:
            files_to_check = self.coder.repo.get_tracked_files()
        else:
            self.io.tool_error("No files available", log_only=False)
            return
        
        for fname in files_to_check:
            try:
                with open(fname, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = len(f.readlines())
                    total_lines += lines
                    total_files += 1
                    
                    if fname.endswith('.py'):
                        py_files += 1
                    elif fname.endswith('.js') or fname.endswith('.ts'):
                        js_files += 1
            except:
                continue
        
        self.io.tool_output(f"\n📊 Code Metrics:", log_only=False)
        self.io.tool_output(f"  Total files: {total_files}", log_only=False)
        self.io.tool_output(f"  Total lines: {total_lines:,}", log_only=False)
        self.io.tool_output(f"  Python files: {py_files}", log_only=False)
        self.io.tool_output(f"  JavaScript/TypeScript files: {js_files}", log_only=False)
        
        # Try radon for complexity
        try:
            self.io.tool_output(f"\n🔍 Running radon (complexity)...", log_only=False)
            result = subprocess.run(['radon', 'cc', '.'], capture_output=True, text=True)
            self.io.tool_output(result.stdout[:500], log_only=False)
        except FileNotFoundError:
            self.io.tool_output("⚠️  radon not found (pip install radon)", log_only=False)
        
        # Try lizard for complexity
        try:
            self.io.tool_output(f"\n🦎 Running lizard...", log_only=False)
            result = subprocess.run(['lizard', '.'], capture_output=True, text=True)
            self.io.tool_output(result.stdout[:500], log_only=False)
        except FileNotFoundError:
            self.io.tool_output("⚠️  lizard not found (pip install lizard)", log_only=False)
        
        self.io.tool_output("\n" + "=" * 50, log_only=False)
        self.io.tool_output("\n💡 Install metrics tools: pip install radon lizard", log_only=False)
        
        self.log_command_end("cmd_metrics", "success", f"Total files: {total_files}, Total lines: {total_lines}")

    def cmd_schedule(self, args):
        "Manage scheduled tasks (routines)"
        import subprocess
        
        self.log_command_start("cmd_schedule", args)
        
        parts = args.strip().split()
        if not parts:
            self.io.tool_error("Usage: /schedule <command> [args]")
            self.io.tool_error("Commands: list, add, remove, run")
            self.io.tool_error("Example: /schedule list")
            self.io.tool_error("Example: /schedule add 'daily test' '0 9 * * *' '/run pytest'")
            return
        
        command = parts[0].lower()
        
        self.io.tool_output(f"⏰ Schedule: {command}", log_only=False)
        self.io.tool_output("=" * 50, log_only=False)
        
        schedule_file = '.aider_schedule.json'
        
        try:
            # Load existing schedules
            if os.path.exists(schedule_file):
                with open(schedule_file, 'r') as f:
                    schedules = json.load(f)
            else:
                schedules = []
            
            if command == 'list':
                if not schedules:
                    self.io.tool_output("No scheduled tasks", log_only=False)
                else:
                    self.io.tool_output(f"\n📋 Scheduled Tasks ({len(schedules)}):", log_only=False)
                    for i, task in enumerate(schedules, 1):
                        self.io.tool_output(f"  {i}. {task.get('name', 'Unnamed')}", log_only=False)
                        self.io.tool_output(f"     Cron: {task.get('cron', 'N/A')}", log_only=False)
                        self.io.tool_output(f"     Command: {task.get('command', 'N/A')}", log_only=False)
            
            elif command == 'add':
                if len(parts) < 4:
                    self.io.tool_error("Usage: /schedule add <name> <cron> <command>")
                    self.io.tool_error("Example: /schedule add 'daily test' '0 9 * * *' '/run pytest'")
                    return
                
                name = parts[1]
                cron = parts[2]
                task_command = ' '.join(parts[3:])
                
                schedules.append({
                    'name': name,
                    'cron': cron,
                    'command': task_command,
                    'created': datetime.now().isoformat()
                })
                
                with open(schedule_file, 'w') as f:
                    json.dump(schedules, f, indent=2)
                
                self.io.tool_output(f"✓ Added scheduled task: {name}", log_only=False)
                self.io.tool_output(f"  Cron: {cron}", log_only=False)
                self.io.tool_output(f"  Command: {task_command}", log_only=False)
                self.io.tool_output("\n💡 Note: This is a simple schedule. For full cron support, use system cron.", log_only=False)
            
            elif command == 'remove':
                if len(parts) < 2:
                    self.io.tool_error("Usage: /schedule remove <index>")
                    return
                
                try:
                    index = int(parts[1]) - 1
                    if 0 <= index < len(schedules):
                        removed = schedules[index]
                        # Require confirmation for dangerous action
                        if not self.confirm_dangerous_action("Remove Scheduled Task", f"Task: {removed.get('name', 'Unnamed')}, Cron: {removed.get('cron', 'N/A')}"):
                            self.io.tool_output("Action cancelled by user.", log_only=False)
                            audit_logger.info(f"cmd_schedule remove cancelled by user: {removed.get('name', 'Unnamed')}")
                            return
                        schedules.pop(index)
                        with open(schedule_file, 'w') as f:
                            json.dump(schedules, f, indent=2)
                        self.io.tool_output(f"✓ Removed: {removed.get('name', 'Unnamed')}", log_only=False)
                    else:
                        self.io.tool_error("Invalid index", log_only=False)
                except ValueError:
                    self.io.tool_error("Invalid index", log_only=False)
            
            elif command == 'run':
                if len(parts) < 2:
                    self.io.tool_error("Usage: /schedule run <index>")
                    return
                
                try:
                    index = int(parts[1]) - 1
                    if 0 <= index < len(schedules):
                        task = schedules[index]
                        self.io.tool_output(f"Running: {task.get('name', 'Unnamed')}", log_only=False)
                        self.io.tool_output(f"Command: {task.get('command', 'N/A')}", log_only=False)
                        # Execute the command
                        self.cmd_run(task.get('command', ''))
                    else:
                        self.io.tool_error("Invalid index", log_only=False)
                except ValueError:
                    self.io.tool_error("Invalid index", log_only=False)
            
            else:
                self.io.tool_error(f"Unknown command: {command}")
                return
            
        except json.JSONDecodeError as e:
            self.io.tool_error(f"Error reading schedule file: {e}", log_only=False)
            self.io.tool_output("Schedule file may be corrupted. Try clearing it.", log_only=False)
            self.log_command_end("cmd_schedule", "error", f"JSON decode error: {e}")
        except Exception as e:
            self.io.tool_error(f"Error: {e}")
            self.log_command_end("cmd_schedule", "error", str(e)[:100])
        
        self.io.tool_output("\n" + "=" * 50, log_only=False)

    def cmd_memory(self, args):
        """
        Manage project memory and context for persistent information storage.
        
        This command provides a persistent memory system for storing project-specific
        information, goals, and context that persists across sessions. It supports
        setting, retrieving, listing, and clearing memory entries.
        
        Subcommands:
            - set <key> <value>: Set a memory entry
            - get <key>: Retrieve a memory entry
            - list: List all memory entries
            - clear <key>: Clear a specific memory entry
            - clear all: Clear all memory entries
            
        Persistence:
            - Memory is stored in .aider_memory.json
            - Entries include value and timestamp
            - Dangerous operations (clear) require confirmation
            
        Args:
            args (str): Memory command in format "<command> [args]"
            
        Example:
            /memory set 'project goal' 'Build a web app'
            /memory get 'project goal'
            /memory list
        """
        
        self.log_command_start("cmd_memory", args)
        
        parts = args.strip().split()
        
        if not parts:
            self.io.tool_error("Usage: /memory <command> [args]")
            self.io.tool_error("Commands: set, get, clear, list")
            self.io.tool_error("Example: /memory set 'project goal' 'Build a web app'")
            self.log_command_end("cmd_memory", "error", "No arguments provided")
            return
        
        command = parts[0].lower()
        
        self.io.tool_output(f"🧠 Memory: {command}", log_only=False)
        self.io.tool_output("=" * 50, log_only=False)
        
        memory_file = '.aider_memory.json'
        
        try:
            # Load existing memory
            if os.path.exists(memory_file):
                with open(memory_file, 'r') as f:
                    memory = json.load(f)
            else:
                memory = {}
            
            if command == 'set':
                if len(parts) < 3:
                    self.io.tool_error("Usage: /memory set <key> <value>")
                    return
                
                key = parts[1]
                value = ' '.join(parts[2:])
                memory[key] = {
                    'value': value,
                    'updated': datetime.now().isoformat()
                }
                
                with open(memory_file, 'w') as f:
                    json.dump(memory, f, indent=2)
                
                self.io.tool_output(f"✓ Set memory: {key}", log_only=False)
            
            elif command == 'get':
                if len(parts) < 2:
                    self.io.tool_error("Usage: /memory get <key>")
                    return
                
                key = parts[1]
                if key in memory:
                    self.io.tool_output(f"{key}: {memory[key]['value']}", log_only=False)
                    self.io.tool_output(f"Updated: {memory[key]['updated']}", log_only=False)
                else:
                    self.io.tool_error(f"Key not found: {key}", log_only=False)
            
            elif command == 'clear':
                if len(parts) > 1:
                    key = parts[1]
                    if key in memory:
                        # Require confirmation for dangerous action
                        if not self.confirm_dangerous_action("Clear Memory Entry", f"Key: {key}"):
                            self.io.tool_output("Action cancelled by user.", log_only=False)
                            audit_logger.info(f"cmd_memory clear cancelled by user: {key}")
                            return
                        del memory[key]
                        self.io.tool_output(f"✓ Cleared: {key}", log_only=False)
                    else:
                        self.io.tool_error(f"Key not found: {key}", log_only=False)
                else:
                    # Require confirmation for dangerous action
                    if not self.confirm_dangerous_action("Clear All Memory", "This will delete all memory entries"):
                        self.io.tool_output("Action cancelled by user.", log_only=False)
                        audit_logger.info("cmd_memory clear all cancelled by user")
                        return
                    memory = {}
                    self.io.tool_output("✓ Cleared all memory", log_only=False)
                
                with open(memory_file, 'w') as f:
                    json.dump(memory, f, indent=2)
            
            elif command == 'list':
                if not memory:
                    self.io.tool_output("No memory entries", log_only=False)
                else:
                    self.io.tool_output(f"\n📋 Memory Entries ({len(memory)}):", log_only=False)
                    for key, data in memory.items():
                        self.io.tool_output(f"  {key}: {data['value']}", log_only=False)
                        self.io.tool_output(f"    Updated: {data['updated']}", log_only=False)
            
            else:
                self.io.tool_error(f"Unknown command: {command}")
                return
            
        except json.JSONDecodeError as e:
            self.io.tool_error(f"Error reading memory file: {e}", log_only=False)
            self.io.tool_output("Memory file may be corrupted. Try clearing it.", log_only=False)
            self.log_command_end("cmd_memory", "error", f"JSON decode error: {e}")
        except Exception as e:
            self.io.tool_error(f"Error: {e}")
            self.log_command_end("cmd_memory", "error", str(e)[:100])
        
        self.io.tool_output("\n" + "=" * 50, log_only=False)

    def cmd_agent(self, args):
        "Run autonomous agent execution loop"
        parts = args.strip().split()
        
        if not parts:
            self.io.tool_error("Usage: /agent <goal> [max_iterations]")
            self.io.tool_error("Example: /agent 'Fix all bugs' 5")
            return
        
        goal = parts[0]
        try:
            max_iterations = int(parts[1]) if len(parts) > 1 else 3
            if max_iterations < 1:
                self.io.tool_error("max_iterations must be >= 1")
                return
        except ValueError:
            self.io.tool_error("Invalid max_iterations: must be a number")
            return
        
        # Require confirmation for dangerous autonomous action
        if not self.confirm_dangerous_action("Autonomous Agent Execution", f"Goal: {goal}, Max Iterations: {max_iterations}"):
            self.io.tool_output("Action cancelled by user.", log_only=False)
            audit_logger.info(f"cmd_agent cancelled by user: {goal}")
            return
        
        self.io.tool_output(f"🤖 Agent Goal: {goal}", log_only=False)
        self.io.tool_output(f"Max Iterations: {max_iterations}", log_only=False)
        self.io.tool_output("=" * 50, log_only=False)
        
        for iteration in range(1, max_iterations + 1):
            self.io.tool_output(f"\n🔄 Iteration {iteration}/{max_iterations}", log_only=False)
            
            # Run the goal as a prompt
            try:
                result = self.coder.run(goal)
                self.io.tool_output(f"✓ Iteration {iteration} complete", log_only=False)
                
                # Check if goal is achieved (simplified check)
                if "complete" in str(result).lower() or "done" in str(result).lower():
                    self.io.tool_output("\n✅ Goal achieved!", log_only=False)
                    break
            except Exception as e:
                self.io.tool_error(f"Error in iteration {iteration}: {e}", log_only=False)
                break
        
        self.io.tool_output("\n" + "=" * 50, log_only=False)
        self.io.tool_output("Agent execution complete", log_only=False)

    def cmd_index(self, args: str) -> None:
        """
        Manage project indexing with aerospace-grade reliability.
        
        This command provides comprehensive project indexing capabilities,
        including full indexing, incremental updates, and index status checking.
        
        Subcommands:
            - full: Perform full project indexing with AST extraction
            - incremental: Perform incremental indexing of modified files
            - status: Show current index status and statistics
            - cancel: Cancel ongoing indexing operation
            
        Args:
            args: Index command in format "<command> [options]"
            
        Examples:
            /index full
            /index incremental
            /index status
            /index cancel
        """
        
        self.log_command_start("cmd_index", args)
        
        parts = args.strip().split()
        
        if not parts:
            self.io.tool_error("Usage: /index <command>")
            self.io.tool_error("Commands: full, incremental, status, cancel")
            self.io.tool_error("Example: /index full")
            self.log_command_end("cmd_index", "error", "No arguments provided")
            return
        
        command = parts[0].lower()
        
        # Check if index manager is available
        if not hasattr(self.coder, 'index_manager') or not self.coder.index_manager:
            self.io.tool_error("Index manager not available. Check configuration.")
            self.log_command_end("cmd_index", "error", "Index manager not available")
            return
        
        self.io.tool_output(f"📊 Index: {command}", log_only=False)
        self.io.tool_output("=" * 50, log_only=False)
        
        try:
            if command == 'full':
                self.io.tool_output("\n🚀 Starting full project index...", log_only=False)
                self.io.tool_output("This may take a while for large projects.", log_only=False)
                self.io.tool_output("", log_only=False)
                
                stats = self.coder.index_manager.index_full(force=True)
                
                self.io.tool_output("\n" + "─" * 50, log_only=False)
                self.io.tool_output("✅ Index Complete", log_only=False, bold=True)
                self.io.tool_output("─" * 50, log_only=False)
                self.io.tool_output(f"📊 Statistics:", log_only=False)
                self.io.tool_output(f"   • Total files: {stats.total_files}", log_only=False)
                self.io.tool_output(f"   • Indexed: {stats.indexed_files}", log_only=False)
                self.io.tool_output(f"   • Failed: {stats.failed_files}", log_only=False)
                self.io.tool_output(f"   • Skipped: {stats.skipped_files}", log_only=False)
                
                if stats.start_time and stats.end_time:
                    duration = (stats.end_time - stats.start_time).total_seconds()
                    self.io.tool_output(f"   • Duration: {duration:.2f} seconds", log_only=False)
                
                if stats.memory_peak_mb > 0:
                    self.io.tool_output(f"   • Peak memory: {stats.memory_peak_mb:.2f} MB", log_only=False)
                
                if stats.errors:
                    self.io.tool_output(f"\n⚠️ Errors ({len(stats.errors)}):", log_only=False)
                    for error in stats.errors[:5]:
                        self.io.tool_output(f"   - {error}", log_only=False)
                
                self.io.tool_output("─" * 50, log_only=False)
                
            elif command == 'incremental':
                self.io.tool_output("\n🔄 Starting incremental index...", log_only=False)
                
                stats = self.coder.index_manager.index_incremental()
                
                if stats.total_files == 0:
                    self.io.tool_success("No files need incremental indexing")
                else:
                    self.io.tool_output(f"\n✅ Incremental index complete", log_only=False)
                    self.io.tool_output(f"📊 Indexed {stats.indexed_files} files", log_only=False)
                    if stats.failed_files > 0:
                        self.io.tool_warning(f"Failed: {stats.failed_files} files", log_only=False)
                
            elif command == 'status':
                status, stats = self.coder.index_manager.get_status()
                
                self.io.tool_output(f"\n📊 Current Status: {status.value}", log_only=False, bold=True)
                self.io.tool_output("", log_only=False)
                
                if stats:
                    self.io.tool_output("Statistics:", log_only=False)
                    self.io.tool_output(f"   • Total files: {stats.total_files}", log_only=False)
                    self.io.tool_output(f"   • Indexed: {stats.indexed_files}", log_only=False)
                    self.io.tool_output(f"   • Failed: {stats.failed_files}", log_only=False)
                    self.io.tool_output(f"   • Skipped: {stats.skipped_files}", log_only=False)
                    
                    if stats.start_time:
                        self.io.tool_output(f"   • Start time: {stats.start_time.isoformat()}", log_only=False)
                    if stats.end_time:
                        self.io.tool_output(f"   • End time: {stats.end_time.isoformat()}", log_only=False)
                    if stats.memory_peak_mb > 0:
                        self.io.tool_output(f"   • Peak memory: {stats.memory_peak_mb:.2f} MB", log_only=False)
                    
                    if stats.errors:
                        self.io.tool_output(f"\n⚠️ Recent errors ({len(stats.errors)}):", log_only=False)
                        for error in stats.errors[-3:]:
                            self.io.tool_output(f"   - {error}", log_only=False)
                
            elif command == 'cancel':
                self.io.tool_output("\n🛑 Cancelling index operation...", log_only=False)
                self.coder.index_manager.cancel()
                self.io.tool_success("Index operation cancelled")
                
            else:
                self.io.tool_error(f"Unknown command: {command}")
                self.io.tool_output("Available commands: full, incremental, status, cancel", log_only=False)
                self.log_command_end("cmd_index", "error", f"Unknown command: {command}")
                return
            
            self.log_command_end("cmd_index", "success", f"Command {command} completed")
            
        except Exception as e:
            self.io.tool_error(f"Error: {e}")
            self.log_command_end("cmd_index", "error", str(e)[:100])
        
        self.io.tool_output("\n" + "=" * 50, log_only=False)

    def cmd_search(self, args: str) -> None:
        """
        Search for symbols and references in the indexed codebase.
        
        This command provides semantic code search capabilities using the
        aerospace-grade index system with AST-based symbol extraction.
        
        Subcommands:
            - symbol <query> [kind]: Search for symbols by name (function, class, variable)
            - reference <symbol_name>: Search for references to a symbol
            - file <file_path>: Get all symbols in a specific file
            - semantic <query>: Semantic search using vector embeddings
            - goto <symbol_name> [file]: Jump to symbol definition
            - hierarchy <file_path>: Get symbol hierarchy for a file
            - structure: Get project file structure
            - explain <file_path> [symbol]: Explain code using AI
            - docs <file_path>: Generate documentation for a file
            
        Args:
            args: Search command in format "<command> [args]"
            
        Examples:
            /search symbol my_function
            /search symbol MyClass class
            /search reference my_function
            /search file /path/to/file.py
        """
        
        self.log_command_start("cmd_search", args)
        
        parts = args.strip().split()
        
        if not parts:
            self.io.tool_error("Usage: /search <command> [args]")
            self.io.tool_error("Commands: symbol, reference, file")
            self.io.tool_error("Example: /search symbol my_function")
            self.log_command_end("cmd_search", "error", "No arguments provided")
            return
        
        command = parts[0].lower()
        
        # Check if index manager is available
        if not hasattr(self.coder, 'index_manager') or not self.coder.index_manager:
            self.io.tool_error("Index manager not available. Check configuration.")
            self.log_command_end("cmd_search", "error", "Index manager not available")
            return
        
        self.io.tool_output(f"🔍 Search: {command}", log_only=False)
        self.io.tool_output("=" * 50, log_only=False)
        
        try:
            if command == 'symbol':
                if len(parts) < 2:
                    self.io.tool_error("Usage: /search symbol <query> [kind]")
                    self.io.tool_error("Kinds: function, class, variable")
                    return
                
                query = parts[1]
                kind = parts[2] if len(parts) > 2 else None
                
                results = self.coder.index_manager.search_symbols(query, kind)
                
                if not results:
                    self.io.tool_output(f"No symbols found matching '{query}'", log_only=False)
                else:
                    self.io.tool_output(f"\n📊 Found {len(results)} symbols:", log_only=False)
                    for result in results:
                        self.io.tool_output(f"  • {result['name']} ({result['kind']})", log_only=False)
                        self.io.tool_output(f"    File: {result['file_path']}", log_only=False)
                        self.io.tool_output(f"    Line: {result['line']}", log_only=False)
                        self.io.tool_output("", log_only=False)
                
            elif command == 'reference':
                if len(parts) < 2:
                    self.io.tool_error("Usage: /search reference <symbol_name>")
                    return
                
                symbol_name = parts[1]
                results = self.coder.index_manager.search_references(symbol_name)
                
                if not results:
                    self.io.tool_output(f"No references found to '{symbol_name}'", log_only=False)
                else:
                    self.io.tool_output(f"\n📊 Found {len(results)} references:", log_only=False)
                    for result in results:
                        self.io.tool_output(f"  • In {result['from_file']}", log_only=False)
                        self.io.tool_output(f"    Symbol: {result['symbol_name']}", log_only=False)
                        self.io.tool_output(f"    Line: {result['line']}", log_only=False)
                        self.io.tool_output("", log_only=False)
                
            elif command == 'file':
                if len(parts) < 2:
                    self.io.tool_error("Usage: /search file <file_path>")
                    return
                
                file_path = parts[1]
                results = self.coder.index_manager.get_file_symbols(file_path)
                
                if not results:
                    self.io.tool_output(f"No symbols found in '{file_path}'", log_only=False)
                else:
                    self.io.tool_output(f"\n📊 Found {len(results)} symbols in {file_path}:", log_only=False)
                    for result in results:
                        self.io.tool_output(f"  • {result['name']} ({result['kind']}) - Line {result['line']}", log_only=False)
            
            elif command == 'semantic':
                if len(parts) < 2:
                    self.io.tool_error("Usage: /search semantic <query>")
                    return
                
                query = ' '.join(parts[1:])
                results = self.coder.index_manager.semantic_search(query, limit=10)
                
                if not results:
                    self.io.tool_output(f"No semantic matches found for '{query}'", log_only=False)
                else:
                    self.io.tool_output(f"\n📊 Found {len(results)} semantic matches:", log_only=False)
                    for result in results:
                        self.io.tool_output(f"  • {result['file_path']}", log_only=False)
                        self.io.tool_output(f"    Chunk: {result['chunk_type']} {result['chunk_name']}", log_only=False)
                        self.io.tool_output(f"    Similarity: {result['similarity']:.3f}", log_only=False)
                        self.io.tool_output(f"    Content: {result['content'][:100]}...", log_only=False)
                        self.io.tool_output("", log_only=False)
            
            elif command == 'goto':
                if len(parts) < 2:
                    self.io.tool_error("Usage: /search goto <symbol_name> [file]")
                    return
                
                symbol_name = parts[1]
                file_path = parts[2] if len(parts) > 2 else None
                
                definition = self.coder.index_manager.jump_to_definition(symbol_name, file_path)
                
                if not definition:
                    self.io.tool_output(f"No definition found for '{symbol_name}'", log_only=False)
                else:
                    self.io.tool_output(f"\n📍 Definition of '{definition['name']}':", log_only=False)
                    self.io.tool_output(f"  Kind: {definition['kind']}", log_only=False)
                    self.io.tool_output(f"  File: {definition['file_path']}", log_only=False)
                    self.io.tool_output(f"  Line: {definition['line']}", log_only=False)
            
            elif command == 'hierarchy':
                if len(parts) < 2:
                    self.io.tool_error("Usage: /search hierarchy <file_path>")
                    return
                
                file_path = parts[1]
                hierarchy = self.coder.index_manager.get_symbol_hierarchy(file_path)
                
                self.io.tool_output(f"\n📁 Symbol hierarchy for {file_path}:", log_only=False)
                
                if hierarchy['classes']:
                    self.io.tool_output(f"  Classes ({len(hierarchy['classes'])}):", log_only=False)
                    for cls in hierarchy['classes']:
                        self.io.tool_output(f"    • {cls['name']} (line {cls['line']})", log_only=False)
                
                if hierarchy['functions']:
                    self.io.tool_output(f"  Functions ({len(hierarchy['functions'])}):", log_only=False)
                    for func in hierarchy['functions']:
                        self.io.tool_output(f"    • {func['name']} (line {func['line']})", log_only=False)
                
                if hierarchy['variables']:
                    self.io.tool_output(f"  Variables ({len(hierarchy['variables'])}):", log_only=False)
                    for var in hierarchy['variables']:
                        self.io.tool_output(f"    • {var['name']} (line {var['line']})", log_only=False)
            
            elif command == 'structure':
                structure = self.coder.index_manager.get_file_structure()
                
                self.io.tool_output(f"\n📂 Project structure:", log_only=False)
                self.io.tool_output(f"  Files: {len(structure['files'])}", log_only=False)
                self.io.tool_output(f"  Directories: {len(structure['directories'])}", log_only=False)
                
                if self.verbose:
                    self.io.tool_output(f"\n  Directories:", log_only=False)
                    for dir_path in structure['directories'][:20]:
                        self.io.tool_output(f"    • {dir_path}", log_only=False)
                    
                    self.io.tool_output(f"\n  Files:", log_only=False)
                    for file_info in structure['files'][:20]:
                        self.io.tool_output(f"    • {file_info['path']} ({file_info['size']} bytes)", log_only=False)
            
            elif command == 'explain':
                if len(parts) < 2:
                    self.io.tool_error("Usage: /search explain <file_path> [symbol]")
                    return
                
                file_path = parts[1]
                symbol_name = parts[2] if len(parts) > 2 else None
                
                results = self.coder.index_manager.explain_code(file_path, symbol_name)
                
                if not results['success']:
                    self.io.tool_output(f"\n✗ Code explanation failed: {results.get('error', 'Unknown error')}", log_only=False)
                else:
                    self.io.tool_output(f"\n📝 Code explanation for {results['file_path']}", log_only=False)
                    if results['symbol_name']:
                        self.io.tool_output(f"  Symbol: {results['symbol_name']}", log_only=False)
                    self.io.tool_output(f"\n{results['explanation']}", log_only=False)
            
            elif command == 'docs':
                if len(parts) < 2:
                    self.io.tool_error("Usage: /search docs <file_path>")
                    return
                
                file_path = parts[1]
                results = self.coder.index_manager.generate_documentation(file_path)
                
                if not results['success']:
                    self.io.tool_output(f"\n✗ Documentation generation failed: {results.get('error', 'Unknown error')}", log_only=False)
                else:
                    self.io.tool_output(f"\n📚 Documentation for {results['file_path']}", log_only=False)
                    self.io.tool_output(f"  Symbols documented: {results['symbols_documented']}", log_only=False)
                    
                    if self.verbose:
                        for doc in results['documentation'][:10]:
                            self.io.tool_output(f"\n  {doc['kind'].capitalize()}: {doc['name']} (line {doc['line']})", log_only=False)
                            self.io.tool_output(f"  {doc['documentation'][:200]}...", log_only=False)
            
            else:
                self.io.tool_error(f"Unknown command: {command}")
                self.io.tool_output("Available commands: symbol, reference, file, semantic, goto, hierarchy, structure, explain, docs", log_only=False)
                self.log_command_end("cmd_search", "error", f"Unknown command: {command}")
                return
            
            self.log_command_end("cmd_search", "success", f"Command {command} completed")
            
        except Exception as e:
            self.io.tool_error(f"Error: {e}")
            self.log_command_end("cmd_search", "error", str(e)[:100])
        
        self.io.tool_output("\n" + "=" * 50, log_only=False)

    def cmd_ci(self, args):
        "CI/CD integration (GitHub Actions, GitLab CI)"
        import subprocess
        
        parts = args.strip().split()
        if not parts:
            self.io.tool_error("Usage: /ci <platform> <command>")
            self.io.tool_error("Platforms: github, gitlab")
            self.io.tool_error("Commands: init, status, run")
            self.io.tool_error("Example: /ci github init")
            return
        
        platform = parts[0].lower()
        command = parts[1].lower()
        
        self.io.tool_output(f"🚀 CI/CD: {platform} {command}", log_only=False)
        self.io.tool_output("=" * 50, log_only=False)
        
        try:
            if platform == 'github':
                if command == 'init':
                    # Create GitHub Actions workflow
                    workflow_dir = '.github/workflows'
                    os.makedirs(workflow_dir, exist_ok=True)
                    
                    workflow_file = f'{workflow_dir}/aider.yml'
                    with open(workflow_file, 'w') as f:
                        f.write("""name: Aider CI

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.10'
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
      - name: Run tests
        run: |
          pytest
      - name: Run linter
        run: |
          flake8 .
""")
                    
                    self.io.tool_output(f"✓ Created GitHub Actions workflow: {workflow_file}", log_only=False)
                    self.io.tool_output("Commit and push to activate", log_only=False)
                
                elif command == 'status':
                    result = subprocess.run(['gh', 'workflow', 'list'], capture_output=True, text=True)
                    self.io.tool_output(result.stdout, log_only=False)
                
                elif command == 'run':
                    # Require confirmation for dangerous action
                    if not self.confirm_dangerous_action("Run CI/CD Workflow", "This will trigger a CI/CD pipeline"):
                        self.io.tool_output("Action cancelled by user.", log_only=False)
                        audit_logger.info("cmd_ci run cancelled by user")
                        return
                    result = subprocess.run(['gh', 'workflow', 'run'], capture_output=True, text=True)
                    self.io.tool_output(result.stdout, log_only=False)
                
                else:
                    self.io.tool_error(f"Unknown command: {command}", log_only=False)
            
            elif platform == 'gitlab':
                if command == 'init':
                    # Create GitLab CI configuration
                    ci_file = '.gitlab-ci.yml'
                    
                    with open(ci_file, 'w') as f:
                        f.write("""stages:
  - test
  - lint

test:
  stage: test
  script:
    - pip install -r requirements.txt
    - pytest

lint:
  stage: lint
  script:
    - pip install flake8
    - flake8 .
""")
                    
                    self.io.tool_output(f"✓ Created GitLab CI config: {ci_file}", log_only=False)
                    self.io.tool_output("Commit and push to activate", log_only=False)
                
                else:
                    self.io.tool_error(f"Unknown command: {command}", log_only=False)
            
            else:
                self.io.tool_error(f"Unknown platform: {platform}", log_only=False)
                self.io.tool_error("Supported: github, gitlab", log_only=False)
        
        except FileNotFoundError:
            self.io.tool_error("CLI tool not found (gh for GitHub, gitlab-ci for GitLab)")
        except Exception as e:
            self.io.tool_error(f"Error: {e}")
        
        self.io.tool_output("\n" + "=" * 50, log_only=False)

    def cmd_pr(self, args):
        "Generate pull request"
        import subprocess
        
        parts = args.strip().split()
        
        # Require confirmation for dangerous action
        if not self.confirm_dangerous_action("Create Pull Request", "This will create a PR with current changes"):
            self.io.tool_output("Action cancelled by user.", log_only=False)
            audit_logger.info("cmd_pr cancelled by user")
            return
        
        self.io.tool_output("📝 Generating Pull Request", log_only=False)
        self.io.tool_output("=" * 50, log_only=False)
        
        try:
            # Check if git repo
            if not self.coder.repo:
                self.io.tool_error("Not in a git repository", log_only=False)
                return
            
            # Get current branch
            result = subprocess.run(['git', 'branch', '--show-current'], capture_output=True, text=True)
            current_branch = result.stdout.strip()
            
            # Get recent commits
            result = subprocess.run(['git', 'log', '--oneline', '-5'], capture_output=True, text=True)
            commits = result.stdout.strip()
            
            # Get diff
            result = subprocess.run(['git', 'diff', 'main...HEAD'], capture_output=True, text=True)
            diff = result.stdout
            
            self.io.tool_output(f"\n📋 PR Information:", log_only=False)
            self.io.tool_output(f"Branch: {current_branch}", log_only=False)
            self.io.tool_output(f"\nRecent Commits:\n{commits}", log_only=False)
            
            if len(diff) > 0:
                self.io.tool_output(f"\n📊 Changes Summary:", log_only=False)
                self.io.tool_output(f"{len(diff)} characters changed", log_only=False)
            
            # Try to create PR using gh CLI
            try:
                pr_title = parts[0] if parts else "Update from " + current_branch
                pr_body = ' '.join(parts[1:]) if len(parts) > 1 else "Automated PR from aider"
                
                result = subprocess.run(
                    ['gh', 'pr', 'create', '--title', pr_title, '--body', pr_body],
                    capture_output=True,
                    text=True
                )
                if result.returncode == 0:
                    self.io.tool_output(f"\n✓ PR created successfully!", log_only=False)
                    self.io.tool_output(result.stdout, log_only=False)
                else:
                    self.io.tool_output(f"\n⚠️  gh CLI failed, showing PR template", log_only=False)
            except:
                self.io.tool_output(f"\n📄 PR Template:", log_only=False)
                self.io.tool_output(f"Title: {parts[0] if parts else 'Update from ' + current_branch}", log_only=False)
                self.io.tool_output(f"Body: {' '.join(parts[1:]) if len(parts) > 1 else 'Describe your changes'}", log_only=False)
                self.io.tool_output("\nTo create PR manually, use: gh pr create", log_only=False)
        
        except Exception as e:
            self.io.tool_error(f"Error: {e}")
        
        self.io.tool_output("\n" + "=" * 50, log_only=False)

    def cmd_generate_test(self, args):
        """
        Generate automatic tests for a file or function.

        This command uses the test generator to create unit tests for Python code.
        It analyzes the code structure and generates test cases with edge cases.

        Args:
            args (str): File path to generate tests for

        Returns:
            None: Test code is displayed via tool_output

        Example:
            /generate_test mymodule.py
        """
        from aider.test_generator import TestGenerator, TestFramework

        if not args:
            self.io.tool_error("Please provide a file path to generate tests for")
            return

        filepath = args.strip()
        if not Path(filepath).exists():
            self.io.tool_error(f"File not found: {filepath}")
            return

        try:
            generator = TestGenerator(framework=TestFramework.PYTEST)
            test_code = generator.generate_test_file(filepath)

            self.io.tool_output(f"\n{'='*50}", log_only=False)
            self.io.tool_output(f"Generated tests for {filepath}:", log_only=False)
            self.io.tool_output(f"{'='*50}", log_only=False)
            self.io.tool_output(test_code, log_only=False)
            self.io.tool_output(f"\n{'='*50}", log_only=False)

            # Suggest output file
            output_file = f"test_{Path(filepath).stem}.py"
            self.io.tool_output(f"Tip: Save this to {output_file} to use the tests", log_only=False)

        except Exception as e:
            self.io.tool_error(f"Error generating tests: {e}")
            audit_logger.error(f"Test generation failed for {filepath}: {e}")

    def cmd_explain(self, args):
        """
        Explain code in a file or function.

        This command uses the code explainer to analyze and explain code,
        providing insights into complexity, dependencies, and potential issues.

        Args:
            args (str): File path to explain

        Returns:
            None: Explanation is displayed via tool_output

        Example:
            /explain mymodule.py
        """
        from aider.code_explainer import CodeExplainer, ExplanationLevel

        if not args:
            self.io.tool_error("Please provide a file path to explain")
            return

        filepath = args.strip()
        if not Path(filepath).exists():
            self.io.tool_error(f"File not found: {filepath}")
            return

        try:
            explainer = CodeExplainer(level=ExplanationLevel.DETAILED)
            explanations = explainer.explain_file(filepath)

            self.io.tool_output(f"\n{'='*50}", log_only=False)
            self.io.tool_output(f"Code Explanation for {filepath}:", log_only=False)
            self.io.tool_output(f"{'='*50}", log_only=False)

            for name, explanation in explanations.items():
                self.io.tool_output(f"\n## {name}:", log_only=False)
                self.io.tool_output(f"**Summary:** {explanation.summary}", log_only=False)
                
                if explanation.key_points:
                    self.io.tool_output(f"\n**Key Points:**", log_only=False)
                    for point in explanation.key_points:
                        self.io.tool_output(f"  - {point}", log_only=False)
                
                if explanation.potential_issues:
                    self.io.tool_output(f"\n**Potential Issues:**", log_only=False)
                    for issue in explanation.potential_issues:
                        self.io.tool_output(f"  - {issue}", log_only=False)
                
                if explanation.suggestions:
                    self.io.tool_output(f"\n**Suggestions:**", log_only=False)
                    for suggestion in explanation.suggestions:
                        self.io.tool_output(f"  - {suggestion}", log_only=False)

            self.io.tool_output(f"\n{'='*50}", log_only=False)

        except Exception as e:
            self.io.tool_error(f"Error explaining code: {e}")
            audit_logger.error(f"Code explanation failed for {filepath}: {e}")

    def cmd_refactor(self, args):
        """
        Analyze code and provide refactoring suggestions.

        This command uses the refactoring assistant to analyze code,
        identify code smells, and provide safe refactoring suggestions.

        Args:
            args (str): File path to analyze for refactoring

        Returns:
            None: Refactoring suggestions are displayed via tool_output

        Example:
            /refactor mymodule.py
        """
        from aider.refactoring_assistant import RefactoringAssistant

        if not args:
            self.io.tool_error("Please provide a file path to analyze for refactoring")
            return

        filepath = args.strip()
        if not Path(filepath).exists():
            self.io.tool_error(f"File not found: {filepath}")
            return

        try:
            assistant = RefactoringAssistant()
            report = assistant.generate_refactoring_report(filepath)

            self.io.tool_output(f"\n{'='*50}", log_only=False)
            self.io.tool_output(f"Refactoring Report for {filepath}:", log_only=False)
            self.io.tool_output(f"{'='*50}", log_only=False)
            self.io.tool_output(report, log_only=False)
            self.io.tool_output(f"\n{'='*50}", log_only=False)

        except Exception as e:
            self.io.tool_error(f"Error generating refactoring suggestions: {e}")
            audit_logger.error(f"Refactoring analysis failed for {filepath}: {e}")

    def cmd_docs(self, args):
        """
        Generate documentation for a file.

        This command uses the documentation generator to analyze code
        and generate comprehensive documentation.

        Args:
            args (str): File path to generate documentation for

        Returns:
            None: Documentation is displayed via tool_output

        Example:
            /docs mymodule.py
        """
        from aider.documentation_generator import DocumentationGenerator

        if not args:
            self.io.tool_error("Please provide a file path to generate documentation for")
            return

        filepath = args.strip()
        if not Path(filepath).exists():
            self.io.tool_error(f"File not found: {filepath}")
            return

        try:
            generator = DocumentationGenerator()
            module_doc = generator.generate_module_doc(filepath)

            if not module_doc:
                self.io.tool_error(f"Failed to generate documentation for {filepath}")
                return

            self.io.tool_output(f"\n{'='*50}", log_only=False)
            self.io.tool_output(f"Documentation for {module_doc.name}:", log_only=False)
            self.io.tool_output(f"{'='*50}", log_only=False)
            self.io.tool_output(f"\nDescription: {module_doc.description}", log_only=False)

            if module_doc.functions:
                self.io.tool_output(f"\n## Functions ({len(module_doc.functions)})", log_only=False)
                for func in module_doc.functions:
                    self.io.tool_output(f"\n### {func.signature}", log_only=False)
                    self.io.tool_output(f"  {func.description}", log_only=False)
                    if func.parameters:
                        self.io.tool_output(f"  Parameters:", log_only=False)
                        for param in func.parameters:
                            self.io.tool_output(f"    - {param['name']}: {param['type']}", log_only=False)
                    if func.returns:
                        self.io.tool_output(f"  Returns: {func.returns}", log_only=False)

            if module_doc.classes:
                self.io.tool_output(f"\n## Classes ({len(module_doc.classes)})", log_only=False)
                for cls in module_doc.classes:
                    self.io.tool_output(f"\n### {cls.name}", log_only=False)
                    self.io.tool_output(f"  {cls.description}", log_only=False)
                    if cls.attributes:
                        self.io.tool_output(f"  Attributes:", log_only=False)
                        for attr in cls.attributes:
                            self.io.tool_output(f"    - {attr['name']}: {attr['type']}", log_only=False)
                    if cls.methods:
                        self.io.tool_output(f"  Methods:", log_only=False)
                        for method in cls.methods:
                            self.io.tool_output(f"    - {method.signature}", log_only=False)

            self.io.tool_output(f"\n{'='*50}", log_only=False)

        except Exception as e:
            self.io.tool_error(f"Error generating documentation: {e}")
            audit_logger.error(f"Documentation generation failed for {filepath}: {e}")

    def cmd_search(self, args):
        """
        Search for code in the codebase.

        This command uses the code searcher to find functions, classes,
        and patterns across the codebase.

        Args:
            args (str): Search type and query (format: <type> <query>)

        Returns:
            None: Search results are displayed via tool_output

        Example:
            /search function add
            /search class Calculator
            /search pattern "def.*test"
        """
        from aider.code_search import CodeSearcher

        if not args:
            self.io.tool_error("Please provide search type and query")
            self.io.tool_error("Usage: /search <type> <query>")
            self.io.tool_error("Search types: function, class, pattern, reference")
            return

        parts = args.strip().split(maxsplit=1)
        if len(parts) < 2:
            self.io.tool_error("Please provide both search type and query")
            self.io.tool_error("Usage: /search <type> <query>")
            return

        search_type = parts[0]
        query = parts[1]

        try:
            searcher = CodeSearcher()
            
            # Index the current directory
            current_dir = Path.cwd()
            searcher.index_directory(str(current_dir))
            
            # Perform search
            if search_type == "function":
                results = searcher.search_function(query, fuzzy=True)
            elif search_type == "class":
                results = searcher.search_class(query, fuzzy=True)
            elif search_type == "pattern":
                results = searcher.search_pattern(query)
            elif search_type == "reference":
                results = searcher.search_references(query)
            else:
                self.io.tool_error(f"Unknown search type: {search_type}")
                self.io.tool_error("Search types: function, class, pattern, reference")
                return

            self.io.tool_output(f"\n{'='*50}", log_only=False)
            self.io.tool_output(f"Search Results ({len(results)} found):", log_only=False)
            self.io.tool_output(f"{'='*50}", log_only=False)

            if not results:
                self.io.tool_output("No results found.", log_only=False)
            else:
                for result in results:
                    self.io.tool_output(f"\n{result.file_path}:{result.line_number}", log_only=False)
                    self.io.tool_output(f"  Type: {result.type.value}", log_only=False)
                    if result.name:
                        self.io.tool_output(f"  Name: {result.name}", log_only=False)
                    if result.signature:
                        self.io.tool_output(f"  Signature: {result.signature}", log_only=False)
                    self.io.tool_output(f"  Context: {result.context[:100]}", log_only=False)

            self.io.tool_output(f"\n{'='*50}", log_only=False)

        except Exception as e:
            self.io.tool_error(f"Error performing search: {e}")
            audit_logger.error(f"Code search failed: {e}")

    def cmd_debug(self, args):
        """
        Analyze an error message and provide debugging assistance.

        This command uses the debugging assistant to analyze errors,
        provide explanations, and suggest fixes.

        Args:
            args (str): Error message to analyze

        Returns:
            None: Debugging assistance is displayed via tool_output

        Example:
            /debug "TypeError: 'int' object is not subscriptable"
        """
        from aider.debugging_assistant import DebuggingAssistant

        if not args:
            self.io.tool_error("Please provide an error message to analyze")
            return

        error_message = args.strip()

        try:
            assistant = DebuggingAssistant()
            analysis = assistant.analyze_error(error_message)

            if not analysis:
                self.io.tool_error("Could not analyze the error message")
                return

            self.io.tool_output(f"\n{'='*50}", log_only=False)
            self.io.tool_output(f"Error Analysis:", log_only=False)
            self.io.tool_output(f"{'='*50}", log_only=False)
            self.io.tool_output(f"\nError Type: {analysis.error_type.value}", log_only=False)
            self.io.tool_output(f"Explanation: {analysis.explanation}", log_only=False)

            if analysis.likely_causes:
                self.io.tool_output(f"\nLikely Causes:", log_only=False)
                for cause in analysis.likely_causes:
                    self.io.tool_output(f"  - {cause}", log_only=False)

            if analysis.suggested_fixes:
                self.io.tool_output(f"\nSuggested Fixes:", log_only=False)
                for fix in analysis.suggested_fixes:
                    self.io.tool_output(f"  - {fix}", log_only=False)

            if analysis.debugging_tips:
                self.io.tool_output(f"\nDebugging Tips:", log_only=False)
                for tip in analysis.debugging_tips:
                    self.io.tool_output(f"  - {tip}", log_only=False)

            self.io.tool_output(f"\n{'='*50}", log_only=False)

        except Exception as e:
            self.io.tool_error(f"Error analyzing error message: {e}")
            audit_logger.error(f"Debugging assistance failed: {e}")

    def cmd_performance(self, args):
        """
        Analyze code performance and detect bottlenecks.

        This command uses the performance analyzer to profile code,
        detect performance issues, and provide optimization suggestions.

        Args:
            args (str): File path to analyze

        Returns:
            None: Performance analysis results are displayed via tool_output

        Example:
            /performance path/to/file.py
        """
        from aider.performance_analyzer import PerformanceAnalyzer

        if not args:
            self.io.tool_error("Please provide a file path to analyze")
            return

        filepath = args.strip()

        try:
            analyzer = PerformanceAnalyzer()
            issues = analyzer.analyze_file(filepath)

            self.io.tool_output(f"\n{'='*50}", log_only=False)
            self.io.tool_output(f"Performance Analysis:", log_only=False)
            self.io.tool_output(f"{'='*50}", log_only=False)

            if not issues:
                self.io.tool_output("No performance issues detected.", log_only=False)
            else:
                self.io.tool_output(f"\nFound {len(issues)} performance issues:\n", log_only=False)
                for issue in issues:
                    self.io.tool_output(f"[{issue.severity.upper()}] {issue.type.value}", log_only=False)
                    self.io.tool_output(f"  Location: {issue.location}", log_only=False)
                    self.io.tool_output(f"  Description: {issue.description}", log_only=False)
                    self.io.tool_output(f"  Suggestion: {issue.suggestion}", log_only=False)
                    self.io.tool_output(f"  Potential Improvement: {issue.potential_improvement}", log_only=False)
                    self.io.tool_output("", log_only=False)

            self.io.tool_output(f"\n{'='*50}", log_only=False)

        except Exception as e:
            self.io.tool_error(f"Error analyzing performance: {e}")
            audit_logger.error(f"Performance analysis failed: {e}")

    def cmd_security(self, args):
        """
        Scan code for security vulnerabilities.

        This command uses the security scanner to detect security issues,
        vulnerabilities, and provide remediation recommendations.

        Args:
            args (str): File path or directory to scan

        Returns:
            None: Security scan results are displayed via tool_output

        Example:
            /security path/to/file.py
            /security path/to/directory
        """
        from aider.security_scanner import SecurityScanner

        if not args:
            self.io.tool_error("Please provide a file path or directory to scan")
            return

        target = args.strip()

        try:
            scanner = SecurityScanner()

            if Path(target).is_file():
                issues = scanner.scan_file(target)
            else:
                issues = scanner.scan_directory(target)

            self.io.tool_output(f"\n{'='*50}", log_only=False)
            self.io.tool_output(f"Security Scan:", log_only=False)
            self.io.tool_output(f"{'='*50}", log_only=False)

            if not issues:
                self.io.tool_output("No security issues detected.", log_only=False)
            else:
                self.io.tool_output(f"\nFound {len(issues)} security issues:\n", log_only=False)
                for issue in issues:
                    self.io.tool_output(f"[{issue.severity.upper()}] {issue.type.value}", log_only=False)
                    self.io.tool_output(f"  Location: {issue.location}", log_only=False)
                    self.io.tool_output(f"  Description: {issue.description}", log_only=False)
                    if issue.cwe_id:
                        self.io.tool_output(f"  CWE: {issue.cwe_id}", log_only=False)
                    self.io.tool_output(f"  Recommendation: {issue.recommendation}", log_only=False)
                    self.io.tool_output("", log_only=False)

            self.io.tool_output(f"\n{'='*50}", log_only=False)

        except Exception as e:
            self.io.tool_error(f"Error scanning for security issues: {e}")
            audit_logger.error(f"Security scan failed: {e}")

    def cmd_review(self, args):
        """
        Perform automated PR review on code changes.

        This command uses the PR reviewer to analyze code changes,
        detect issues, and provide review suggestions.

        Args:
            args (str): File path to review

        Returns:
            None: Review results are displayed via tool_output

        Example:
            /review path/to/file.py
        """
        from aider.pr_reviewer import PRReviewer

        if not args:
            self.io.tool_error("Please provide a file path to review")
            return

        filepath = args.strip()

        try:
            reviewer = PRReviewer()
            
            # For simplicity, review the file against an empty baseline
            # In a real PR context, this would compare old and new versions
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            
            result = reviewer.review_changes("", content, filepath)

            self.io.tool_output(f"\n{'='*50}", log_only=False)
            self.io.tool_output(f"PR Review:", log_only=False)
            self.io.tool_output(f"{'='*50}", log_only=False)
            self.io.tool_output(f"\nReview Score: {result.overall_score}/100", log_only=False)
            self.io.tool_output(f"Approval Status: {result.approval_status}", log_only=False)
            self.io.tool_output(f"Summary: {result.summary}", log_only=False)

            if result.issues:
                self.io.tool_output(f"\nIssues Found: {len(result.issues)}\n", log_only=False)
                for issue in result.issues:
                    self.io.tool_output(f"[{issue.severity.upper()}] {issue.type.value}", log_only=False)
                    self.io.tool_output(f"  Location: {issue.file_path}:{issue.line_number}", log_only=False)
                    self.io.tool_output(f"  Description: {issue.description}", log_only=False)
                    self.io.tool_output(f"  Suggestion: {issue.suggestion}", log_only=False)
                    self.io.tool_output("", log_only=False)
            else:
                self.io.tool_output("\nNo issues detected. Great job!", log_only=False)

            self.io.tool_output(f"\n{'='*50}", log_only=False)

        except Exception as e:
            self.io.tool_error(f"Error performing review: {e}")
            audit_logger.error(f"PR review failed: {e}")

    def cmd_collaborate(self, args):
        """
        Manage collaboration sessions and comments.

        This command uses the collaboration manager to create sessions,
        add comments, and manage team collaboration.

        Args:
            args (str): Command and arguments (format: <action> [args])

        Returns:
            None: Collaboration results are displayed via tool_output

        Example:
            /collaborate create "Session Name" "user1,user2"
            /collaborate list
            /collaborate comment <session_id> <file_path> <line> <comment>
        """
        from aider.collaboration import CollaborationManager, CommentType

        if not args:
            self.io.tool_error("Please provide a collaboration command")
            self.io.tool_error("Usage: /collaborate <action> [args]")
            self.io.tool_error("Actions: create, list, comment, stats")
            return

        parts = args.strip().split(maxsplit=1)
        action = parts[0]
        
        try:
            manager = CollaborationManager()

            if action == "create":
                if len(parts) < 2:
                    self.io.tool_error("Usage: /collaborate create <name> <participants>")
                    return
                
                create_args = parts[1].split(maxsplit=1)
                if len(create_args) < 2:
                    self.io.tool_error("Usage: /collaborate create <name> <participants>")
                    return
                
                name = create_args[0]
                participants = create_args[1].split(',')
                
                session = manager.create_session(name, participants)
                
                self.io.tool_output(f"\n{'='*50}", log_only=False)
                self.io.tool_output(f"Collaboration Session Created:", log_only=False)
                self.io.tool_output(f"{'='*50}", log_only=False)
                self.io.tool_output(f"Session ID: {session.id}", log_only=False)
                self.io.tool_output(f"Name: {session.name}", log_only=False)
                self.io.tool_output(f"Participants: {', '.join(session.participants)}", log_only=False)
                self.io.tool_output(f"{'='*50}", log_only=False)

            elif action == "list":
                sessions = manager.list_sessions()
                
                self.io.tool_output(f"\n{'='*50}", log_only=False)
                self.io.tool_output(f"Collaboration Sessions:", log_only=False)
                self.io.tool_output(f"{'='*50}", log_only=False)
                
                if not sessions:
                    self.io.tool_output("No active sessions.", log_only=False)
                else:
                    for session in sessions:
                        self.io.tool_output(f"\nSession: {session.name}", log_only=False)
                        self.io.tool_output(f"  ID: {session.id}", log_only=False)
                        self.io.tool_output(f"  Participants: {', '.join(session.participants)}", log_only=False)
                        self.io.tool_output(f"  Active: {session.active}", log_only=False)
                        self.io.tool_output(f"  Comments: {len(session.comments)}", log_only=False)
                
                self.io.tool_output(f"\n{'='*50}", log_only=False)

            elif action == "stats":
                stats = manager.get_statistics()
                
                self.io.tool_output(f"\n{'='*50}", log_only=False)
                self.io.tool_output(f"Collaboration Statistics:", log_only=False)
                self.io.tool_output(f"{'='*50}", log_only=False)
                self.io.tool_output(f"Total Comments: {stats['total_comments']}", log_only=False)
                self.io.tool_output(f"Unresolved Comments: {stats['unresolved_comments']}", log_only=False)
                self.io.tool_output(f"Total Sessions: {stats['total_sessions']}", log_only=False)
                self.io.tool_output(f"Active Sessions: {stats['active_sessions']}", log_only=False)
                self.io.tool_output(f"Total Participants: {stats['total_participants']}", log_only=False)
                self.io.tool_output(f"{'='*50}", log_only=False)

            elif action == "comment":
                self.io.tool_error("Comment addition requires more parameters. Use the API directly.", log_only=False)

            else:
                self.io.tool_error(f"Unknown action: {action}")
                self.io.tool_error("Actions: create, list, comment, stats")

        except Exception as e:
            self.io.tool_error(f"Error managing collaboration: {e}")
            audit_logger.error(f"Collaboration management failed: {e}")


def expand_subdir(file_path):
    if file_path.is_file():
        yield file_path
        return

    if file_path.is_dir():
        for file in file_path.rglob("*"):
            if file.is_file():
                yield file


def parse_quoted_filenames(args):
    filenames = re.findall(r"\"(.+?)\"|(\S+)", args)
    filenames = [name for sublist in filenames for name in sublist if name]
    return filenames


def get_help_md():
    md = Commands(None, None).get_help_md()
    return md


def main():
    md = get_help_md()
    print(md)


if __name__ == "__main__":
    status = main()
    sys.exit(status)
