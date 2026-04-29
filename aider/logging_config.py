"""
Enhanced Logging Configuration Module

This module provides structured logging configuration for the Aider AI coding assistant.
It implements aerospace-level logging with JSON formatting, log rotation, and
comprehensive audit trails.

Key Features:
- Structured JSON logging
- Log rotation and archiving
- Multiple log levels (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- Performance tracking
- Audit trail support
- Thread-safe logging
"""

import json
import logging
import logging.handlers
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


class StructuredFormatter(logging.Formatter):
    """
    Custom formatter that outputs log records as structured JSON.
    
    This formatter provides aerospace-level logging with structured data,
    making logs machine-readable and easier to analyze.
    """
    
    def __init__(self):
        super().__init__()
    
    def format(self, record: logging.LogRecord) -> str:
        """
        Format log record as JSON.
        
        Args:
            record: The log record to format
            
        Returns:
            JSON-formatted log string
        """
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "thread_id": threading.get_ident(),
            "process_id": os.getpid(),
        }
        
        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        
        # Add extra fields if present
        if hasattr(record, "extra_fields"):
            log_data.update(record.extra_fields)
        
        return json.dumps(log_data, default=str)


class PerformanceLogger:
    """
    Performance tracking logger for monitoring system performance.
    
    This class provides aerospace-level performance monitoring with timing,
    memory usage tracking, and performance metrics collection.
    """
    
    def __init__(self, logger_name: str = "aider.performance"):
        """
        Initialize the performance logger.
        
        Args:
            logger_name: Name of the logger instance
        """
        self.logger = logging.getLogger(logger_name)
        self._timings: Dict[str, float] = {}
        self._lock = threading.Lock()
    
    def start_timer(self, operation: str) -> None:
        """
        Start timing an operation.
        
        Args:
            operation: Name of the operation to time
        """
        with self._lock:
            self._timings[operation] = time.time()
    
    def end_timer(self, operation: str) -> Optional[float]:
        """
        End timing an operation and log the duration.
        
        Args:
            operation: Name of the operation to time
            
        Returns:
            Duration in seconds, or None if operation not found
        """
        with self._lock:
            start_time = self._timings.pop(operation, None)
            if start_time is None:
                self.logger.warning(f"Timer not found for operation: {operation}")
                return None
            
            duration = time.time() - start_time
            self.logger.info(
                f"Operation completed: {operation}",
                extra={"extra_fields": {"operation": operation, "duration_seconds": duration}}
            )
            return duration
    
    def log_memory_usage(self) -> None:
        """Log current memory usage."""
        try:
            import psutil
            process = psutil.Process(os.getpid())
            memory_info = process.memory_info()
            self.logger.info(
                "Memory usage",
                extra={
                    "extra_fields": {
                        "rss_mb": memory_info.rss / 1024 / 1024,
                        "vms_mb": memory_info.vms / 1024 / 1024,
                    }
                },
            )
        except ImportError:
            self.logger.warning("psutil not available for memory tracking")


class AuditLogger:
    """
    Audit logger for tracking critical operations and security events.
    
    This class provides aerospace-level audit logging for compliance
    and security monitoring.
    """
    
    def __init__(self, logger_name: str = "aider.audit"):
        """
        Initialize the audit logger.
        
        Args:
            logger_name: Name of the logger instance
        """
        self.logger = logging.getLogger(logger_name)
    
    def log_command_start(self, command: str, args: str = "", user: str = None) -> None:
        """
        Log the start of a command execution.
        
        Args:
            command: Command name
            args: Command arguments
            user: User executing the command (if available)
        """
        self.logger.info(
            f"Command started: {command}",
            extra={
                "extra_fields": {
                    "event_type": "command_start",
                    "command": command,
                    "args": args[:500] if args else "",
                    "user": user,
                }
            },
        )
    
    def log_command_end(self, command: str, status: str, details: str = "") -> None:
        """
        Log the end of a command execution.
        
        Args:
            command: Command name
            status: Execution status (success/failure/error)
            details: Additional details about the execution
        """
        self.logger.info(
            f"Command completed: {command}",
            extra={
                "extra_fields": {
                    "event_type": "command_end",
                    "command": command,
                    "status": status,
                    "details": details[:500] if details else "",
                }
            },
        )
    
    def log_security_event(self, event_type: str, details: str, severity: str = "info") -> None:
        """
        Log a security-related event.
        
        Args:
            event_type: Type of security event
            details: Event details
            severity: Severity level (info/warning/error/critical)
        """
        log_method = getattr(self.logger, severity.lower(), self.logger.info)
        log_method(
            f"Security event: {event_type}",
            extra={
                "extra_fields": {
                    "event_type": "security",
                    "security_event_type": event_type,
                    "details": details[:500] if details else "",
                    "severity": severity,
                }
            },
        )


def setup_logging(
    log_level: str = "INFO",
    log_dir: str = ".aider_logs",
    enable_console: bool = True,
    enable_json: bool = True,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
) -> None:
    """
    Configure enhanced logging for the Aider application.
    
    This function sets up aerospace-level logging with structured JSON output,
    log rotation, and multiple handlers for comprehensive logging.
    
    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_dir: Directory for log files
        enable_console: Enable console output
        enable_json: Enable JSON structured logging
        max_bytes: Maximum size of log file before rotation
        backup_count: Number of backup log files to keep
    """
    # Create log directory
    log_path = Path(log_dir)
    log_path.mkdir(exist_ok=True)
    
    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    
    # Remove existing handlers
    root_logger.handlers.clear()
    
    # JSON file handler for structured logging
    if enable_json:
        json_handler = logging.handlers.RotatingFileHandler(
            log_path / "aider_structured.log",
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        json_handler.setLevel(logging.DEBUG)
        json_handler.setFormatter(StructuredFormatter())
        root_logger.addHandler(json_handler)
    
    # Text file handler for human-readable logs
    text_handler = logging.handlers.RotatingFileHandler(
        log_path / "aider.log",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    text_handler.setLevel(logging.DEBUG)
    text_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    text_handler.setFormatter(text_formatter)
    root_logger.addHandler(text_handler)
    
    # Console handler
    if enable_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        console_handler.setFormatter(console_formatter)
        root_logger.addHandler(console_handler)
    
    # Audit-specific logger
    audit_logger = logging.getLogger("aider.audit")
    audit_handler = logging.handlers.RotatingFileHandler(
        log_path / "aider_audit.log",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    audit_handler.setLevel(logging.INFO)
    audit_handler.setFormatter(text_formatter)
    audit_logger.addHandler(audit_handler)
    audit_logger.propagate = False
    
    # Performance logger
    perf_logger = logging.getLogger("aider.performance")
    perf_handler = logging.handlers.RotatingFileHandler(
        log_path / "aider_performance.log",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    perf_handler.setLevel(logging.DEBUG)
    perf_handler.setFormatter(text_formatter)
    perf_logger.addHandler(perf_handler)
    perf_logger.propagate = False


# Global instances
performance_logger = PerformanceLogger()
audit_logger = AuditLogger()
