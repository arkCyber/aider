"""
Aider Run Command Module

This module provides utilities for running shell commands with proper
output capture, error handling, and cross-platform compatibility.

Key Features:
- Cross-platform command execution (Windows, Linux, macOS)
- Real-time output streaming
- Interactive command support using pexpect
- Subprocess fallback for non-interactive environments
- Error handling and status code reporting
- Parent process detection for shell selection

The module provides two main execution methods:
- run_cmd_pexpect: Interactive execution with pexpect (Unix-like systems)
- run_cmd_subprocess: Non-interactive execution with subprocess (fallback)
"""

import os
import platform
import subprocess
import sys
from io import BytesIO

import pexpect
import psutil


def run_cmd(command, verbose=False, error_print=None, cwd=None, io=None):
    """
    Execute a shell command with appropriate method based on environment.
    
    This function automatically selects the best execution method based on:
    - Terminal type (TTY vs non-TTY)
    - Operating system (Windows vs Unix-like)
    - Available libraries (pexpect availability)
    
    Args:
        command (str): Shell command to execute
        verbose (bool): Enable verbose output for debugging
        error_print (callable): Custom error print function
        cwd (str): Working directory for command execution
        io: IO object for command display
        
    Returns:
        tuple: (exit_code, output) where exit_code is the process return code
               and output is the captured command output
    """
    try:
        # Use pexpect for interactive execution on Unix-like systems with TTY
        if sys.stdin.isatty() and hasattr(pexpect, "spawn") and platform.system() != "Windows":
            return run_cmd_pexpect(command, verbose, cwd, io)

        # Fallback to subprocess for Windows or non-TTY environments
        return run_cmd_subprocess(command, verbose, cwd, io)
    except OSError as e:
        error_message = f"Error occurred while running command '{command}': {str(e)}"
        if error_print is None:
            print(error_message)
        else:
            error_print(error_message)
        return 1, error_message


def get_windows_parent_process_name():
    """
    Detect the parent process name on Windows for shell selection.
    
    This function walks up the process tree to find if the current
    process is running under PowerShell or cmd.exe, which helps
    determine the appropriate shell for command execution.
    
    Returns:
        str or None: Parent process name if found (powershell.exe or cmd.exe),
                     None otherwise
    """
    try:
        current_process = psutil.Process()
        while True:
            parent = current_process.parent()
            if parent is None:
                break
            parent_name = parent.name().lower()
            if parent_name in ["powershell.exe", "cmd.exe"]:
                return parent_name
            current_process = parent
        return None
    except Exception:
        return None


def run_cmd_subprocess(command, verbose=False, cwd=None, encoding=sys.stdout.encoding, io=None):
    """
    Run a shell command using subprocess with real-time output streaming.
    
    This method uses Python's subprocess module to execute commands
    with real-time output streaming. It handles shell selection for
    Windows systems and provides unbuffered output.
    
    Args:
        command (str): Shell command to execute
        verbose (bool): Enable verbose output for debugging
        cwd (str): Working directory for command execution
        encoding (str): Character encoding for output
        io: IO object for command display
        
    Returns:
        tuple: (exit_code, output) where exit_code is the process return code
               and output is the captured command output
    """
    if verbose:
        print("Using run_cmd_subprocess:", command)

    try:
        shell = os.environ.get("SHELL", "/bin/sh")
        parent_process = None

        # Determine the appropriate shell for Windows
        if platform.system() == "Windows":
            parent_process = get_windows_parent_process_name()
            if parent_process == "powershell.exe":
                command = f"powershell -Command {command}"

        if verbose:
            print("Running command:", command)
            print("SHELL:", shell)
            if platform.system() == "Windows":
                print("Parent process:", parent_process)

        # Display command if io is available
        if io and hasattr(io, 'tool_command'):
            io.tool_command(command)

        # Execute command with real-time output streaming
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            shell=True,
            encoding=encoding,
            errors="replace",
            bufsize=0,  # Set bufsize to 0 for unbuffered output
            universal_newlines=True,
            cwd=cwd,
        )

        # Stream output in real-time
        output = []
        while True:
            chunk = process.stdout.read(1)
            if not chunk:
                break
            print(chunk, end="", flush=True)  # Print the chunk in real-time
            output.append(chunk)  # Store the chunk for later use

        process.wait()
        return process.returncode, "".join(output)
    except Exception as e:
        return 1, str(e)


def run_cmd_pexpect(command, verbose=False, cwd=None, io=None):
    """
    Run a shell command interactively using pexpect, capturing all output.

    This method provides interactive command execution with proper
    terminal emulation, allowing for commands that require user
    input or interactive prompts. It uses the pexpect library
    for cross-platform interactive shell execution.

    Args:
        command (str): The command to run as a string
        verbose (bool): If True, print output in real-time for debugging
        cwd (str): Working directory for command execution
        io: IO object for displaying commands

    Returns:
        tuple: (exit_status, output) where exit_status is the process exit code
               and output is the captured command output as a string
    """
    if verbose:
        print("Using run_cmd_pexpect:", command)

    # Display command if io is available
    if io and hasattr(io, 'tool_command'):
        io.tool_command(command)

    output = BytesIO()

    def output_callback(b):
        """
        Callback function to capture pexpect output.
        
        Args:
            b: Bytes output from pexpect
            
        Returns:
            bytes: The input bytes for filtering
        """
        output.write(b)
        return b

    try:
        # Use the SHELL environment variable, falling back to /bin/sh if not set
        shell = os.environ.get("SHELL", "/bin/sh")
        if verbose:
            print("With shell:", shell)

        if os.path.exists(shell):
            # Use the shell from SHELL environment variable
            if verbose:
                print("Running pexpect.spawn with shell:", shell)
            child = pexpect.spawn(shell, args=["-i", "-c", command], encoding="utf-8", cwd=cwd)
        else:
            # Fall back to spawning the command directly
            if verbose:
                print("Running pexpect.spawn without shell.")
            child = pexpect.spawn(command, encoding="utf-8", cwd=cwd)

        # Transfer control to the user, capturing output
        child.interact(output_filter=output_callback)

        # Wait for the command to finish and get the exit status
        child.close()
        return child.exitstatus, output.getvalue().decode("utf-8", errors="replace")

    except (pexpect.ExceptionPexpect, TypeError, ValueError) as e:
        error_msg = f"Error running command {command}: {e}"
        return 1, error_msg
