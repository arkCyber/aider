"""
Unified Error Handling Module

This module provides unified error handling for the Aider AI coding assistant.
It implements aerospace-level error management with classification, recovery strategies,
and retry mechanisms.

Key Features:
- Unified error classification system
- Error recovery strategies
- Automatic retry mechanism with exponential backoff
- Error context and tracking
- Error reporting and logging
- Circuit breaker pattern for failing operations
"""

import functools
import logging
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Type, TypeVar
import inspect


class ErrorCategory(Enum):
    """Error category classification."""
    NETWORK = "network"
    API = "api"
    FILESYSTEM = "filesystem"
    VALIDATION = "validation"
    PERMISSION = "permission"
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class ErrorSeverity(Enum):
    """Error severity levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RecoveryStrategy(Enum):
    """Error recovery strategies."""
    RETRY = "retry"
    FALLBACK = "fallback"
    SKIP = "skip"
    ABORT = "abort"
    USER_INTERVENTION = "user_intervention"


@dataclass
class ErrorContext:
    """
    Context information for an error.
    
    Attributes:
        error_type: Type of the error
        error_message: Error message
        error_category: Category of the error
        severity: Severity of the error
        timestamp: When the error occurred
        stack_trace: Stack trace of the error
        metadata: Additional error metadata
        recovery_strategy: Suggested recovery strategy
    """
    error_type: Type[Exception]
    error_message: str
    error_category: ErrorCategory
    severity: ErrorSeverity
    timestamp: datetime = field(default_factory=datetime.utcnow)
    stack_trace: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    recovery_strategy: RecoveryStrategy = RecoveryStrategy.ABORT


@dataclass
class RetryConfig:
    """
    Configuration for retry behavior.
    
    Attributes:
        max_attempts: Maximum number of retry attempts
        base_delay: Base delay between retries in seconds
        max_delay: Maximum delay between retries in seconds
        exponential_backoff: Whether to use exponential backoff
        jitter: Whether to add jitter to delay
        retry_on: List of exception types to retry on
        retry_on_categories: List of error categories to retry on
    """
    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    exponential_backoff: bool = True
    jitter: bool = True
    retry_on: List[Type[Exception]] = field(default_factory=list)
    retry_on_categories: List[ErrorCategory] = field(default_factory=list)


class ErrorHandler:
    """
    Unified error handler with classification and recovery strategies.
    
    This class provides aerospace-level error management with comprehensive
    error handling capabilities.
    """
    
    def __init__(self):
        """Initialize the error handler."""
        self._error_history: List[ErrorContext] = []
        self._error_counts: Dict[str, int] = {}
        self._circuit_breakers: Dict[str, Dict[str, Any]] = {}
        self._logger = logging.getLogger("aider.error_handler")
    
    def classify_error(self, error: Exception) -> ErrorContext:
        """
        Classify an error and determine recovery strategy.
        
        Args:
            error: The exception to classify
            
        Returns:
            ErrorContext with classification information
        """
        error_type = type(error)
        error_message = str(error)
        stack_trace = traceback.format_exc()
        
        # Classify error category
        category = self._determine_category(error, error_type)
        
        # Determine severity
        severity = self._determine_severity(error, category)
        
        # Determine recovery strategy
        recovery_strategy = self._determine_recovery_strategy(error, category, severity)
        
        # Create error context
        context = ErrorContext(
            error_type=error_type,
            error_message=error_message,
            error_category=category,
            severity=severity,
            stack_trace=stack_trace,
            recovery_strategy=recovery_strategy,
        )
        
        # Track error
        self._track_error(context)
        
        return context
    
    def _determine_category(self, error: Exception, error_type: Type) -> ErrorCategory:
        """
        Determine the error category.
        
        Args:
            error: The exception
            error_type: Type of the exception
            
        Returns:
            ErrorCategory
        """
        error_name = error_type.__name__.lower()
        error_message = str(error).lower()
        
        # Network errors
        if any(name in error_name for name in ["connection", "network", "http", "url"]):
            return ErrorCategory.NETWORK
        
        # API errors
        if any(name in error_name for name in ["api", "llm", "model"]):
            return ErrorCategory.API
        
        # Filesystem errors
        if any(name in error_name for name in ["file", "io", "path", "notfound"]):
            return ErrorCategory.FILESYSTEM
        
        # Validation errors
        if any(name in error_name for name in ["value", "type", "validation"]):
            return ErrorCategory.VALIDATION
        
        # Permission errors
        if any(name in error_name for name in ["permission", "access", "auth"]):
            return ErrorCategory.PERMISSION
        
        # Timeout errors
        if any(name in error_name for name in ["timeout", "timedout"]):
            return ErrorCategory.TIMEOUT
        
        # Rate limit errors
        if "rate" in error_message or "limit" in error_message:
            return ErrorCategory.RATE_LIMIT
        
        return ErrorCategory.UNKNOWN
    
    def _determine_severity(self, error: Exception, category: ErrorCategory) -> ErrorSeverity:
        """
        Determine the error severity.
        
        Args:
            error: The exception
            category: Error category
            
        Returns:
            ErrorSeverity
        """
        # Critical categories
        if category in [ErrorCategory.PERMISSION, ErrorCategory.CRITICAL]:
            return ErrorSeverity.CRITICAL
        
        # High severity
        if category in [ErrorCategory.FILESYSTEM]:
            return ErrorSeverity.HIGH
        
        # Medium severity
        if category in [ErrorCategory.API, ErrorCategory.NETWORK]:
            return ErrorSeverity.MEDIUM
        
        # Low severity
        if category in [ErrorCategory.VALIDATION, ErrorCategory.TIMEOUT]:
            return ErrorSeverity.LOW
        
        return ErrorSeverity.MEDIUM
    
    def _determine_recovery_strategy(
        self, error: Exception, category: ErrorCategory, severity: ErrorSeverity
    ) -> RecoveryStrategy:
        """
        Determine the recovery strategy.
        
        Args:
            error: The exception
            category: Error category
            severity: Error severity
            
        Returns:
            RecoveryStrategy
        """
        # Rate limit - retry with backoff
        if category == ErrorCategory.RATE_LIMIT:
            return RecoveryStrategy.RETRY
        
        # Timeout - retry
        if category == ErrorCategory.TIMEOUT:
            return RecoveryStrategy.RETRY
        
        # Network errors - retry
        if category == ErrorCategory.NETWORK:
            return RecoveryStrategy.RETRY
        
        # Validation errors - skip or abort
        if category == ErrorCategory.VALIDATION:
            return RecoveryStrategy.SKIP
        
        # Permission errors - user intervention
        if category == ErrorCategory.PERMISSION:
            return RecoveryStrategy.USER_INTERVENTION
        
        # Filesystem errors - fallback or abort
        if category == ErrorCategory.FILESYSTEM:
            return RecoveryStrategy.FALLBACK
        
        # API errors - retry or abort based on severity
        if category == ErrorCategory.API:
            if severity in [ErrorSeverity.LOW, ErrorSeverity.MEDIUM]:
                return RecoveryStrategy.RETRY
            return RecoveryStrategy.ABORT
        
        return RecoveryStrategy.ABORT
    
    def _track_error(self, context: ErrorContext) -> None:
        """
        Track an error for analysis.
        
        Args:
            context: Error context to track
        """
        self._error_history.append(context)
        
        # Keep history limited to last 1000 errors
        if len(self._error_history) > 1000:
            self._error_history = self._error_history[-1000:]
        
        # Update error counts
        error_key = f"{context.error_type.__name__}:{context.error_category.value}"
        self._error_counts[error_key] = self._error_counts.get(error_key, 0) + 1
    
    def handle_error(self, error: Exception, context: Optional[Dict[str, Any]] = None) -> ErrorContext:
        """
        Handle an error with classification and logging.
        
        Args:
            error: The exception to handle
            context: Additional context information
            
        Returns:
            ErrorContext with handling information
        """
        error_context = self.classify_error(error)
        
        if context:
            error_context.metadata.update(context)
        
        # Log the error
        self._log_error(error_context)
        
        return error_context
    
    def _log_error(self, context: ErrorContext) -> None:
        """
        Log an error context.
        
        Args:
            context: Error context to log
        """
        log_method = {
            ErrorSeverity.LOW: self._logger.debug,
            ErrorSeverity.MEDIUM: self._logger.warning,
            ErrorSeverity.HIGH: self._logger.error,
            ErrorSeverity.CRITICAL: self._logger.critical,
        }.get(context.severity, self._logger.error)
        
        log_method(
            f"Error occurred: {context.error_type.__name__} - {context.error_message}",
            extra={
                "category": context.error_category.value,
                "severity": context.severity.value,
                "recovery_strategy": context.recovery_strategy.value,
                "metadata": context.metadata,
            },
        )
    
    def check_circuit_breaker(self, operation_name: str) -> bool:
        """
        Check if circuit breaker is open for an operation.
        
        Args:
            operation_name: Name of the operation to check
            
        Returns:
            True if circuit is closed (operation allowed), False if open
        """
        if operation_name not in self._circuit_breakers:
            return True
        
        breaker = self._circuit_breakers[operation_name]
        
        # Check if breaker should reset
        if breaker["state"] == "open":
            if datetime.utcnow() - breaker["last_failure"] > breaker["reset_timeout"]:
                breaker["state"] = "half_open"
                self._logger.info(f"Circuit breaker for {operation_name} moved to half-open")
                return True
            return False
        
        return breaker["state"] != "open"
    
    def record_failure(self, operation_name: str, reset_timeout_seconds: int = 60) -> None:
        """
        Record a failure for an operation (circuit breaker).
        
        Args:
            operation_name: Name of the operation
            reset_timeout_seconds: Timeout before circuit breaker resets
        """
        if operation_name not in self._circuit_breakers:
            self._circuit_breakers[operation_name] = {
                "state": "closed",
                "failures": 0,
                "failure_threshold": 5,
                "last_failure": None,
                "reset_timeout": timedelta(seconds=reset_timeout_seconds),
            }
        
        breaker = self._circuit_breakers[operation_name]
        breaker["failures"] += 1
        breaker["last_failure"] = datetime.utcnow()
        
        # Open circuit if threshold exceeded
        if breaker["failures"] >= breaker["failure_threshold"]:
            breaker["state"] = "open"
            self._logger.warning(f"Circuit breaker for {operation_name} opened after {breaker['failures']} failures")
    
    def record_success(self, operation_name: str) -> None:
        """
        Record a success for an operation (circuit breaker).
        
        Args:
            operation_name: Name of the operation
        """
        if operation_name in self._circuit_breakers:
            breaker = self._circuit_breakers[operation_name]
            breaker["failures"] = 0
            breaker["state"] = "closed"
    
    def get_error_statistics(self) -> Dict[str, Any]:
        """
        Get error statistics.
        
        Returns:
            Dictionary with error statistics
        """
        return {
            "total_errors": len(self._error_history),
            "error_counts": self._error_counts.copy(),
            "circuit_breakers": {
                name: {
                    "state": breaker["state"],
                    "failures": breaker["failures"],
                }
                for name, breaker in self._circuit_breakers.items()
            },
        }


def with_retry(
    config: Optional[RetryConfig] = None,
    operation_name: Optional[str] = None,
):
    """
    Decorator for automatic retry with exponential backoff.
    
    Args:
        config: Retry configuration
        operation_name: Name of the operation for circuit breaker
        
    Returns:
        Decorator function
    """
    if config is None:
        config = RetryConfig()
    
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            error_handler = ErrorHandler()
            op_name = operation_name or func.__name__
            
            last_exception = None
            
            for attempt in range(config.max_attempts):
                # Check circuit breaker
                if not error_handler.check_circuit_breaker(op_name):
                    raise RuntimeError(f"Circuit breaker open for {op_name}")
                
                try:
                    result = func(*args, **kwargs)
                    
                    # Record success
                    error_handler.record_success(op_name)
                    
                    return result
                
                except Exception as e:
                    last_exception = e
                    context = error_handler.handle_error(e)
                    
                    # Check if we should retry
                    should_retry = (
                        type(e) in config.retry_on
                        or context.error_category in config.retry_on_categories
                    ) if config.retry_on or config.retry_on_categories else True
                    
                    if not should_retry:
                        break
                    
                    # Calculate delay
                    if config.exponential_backoff:
                        delay = min(config.base_delay * (2 ** attempt), config.max_delay)
                    else:
                        delay = config.base_delay
                    
                    if config.jitter:
                        delay *= (0.5 + (hash(op_name + str(attempt)) % 100) / 100)
                    
                    # Don't delay on last attempt
                    if attempt < config.max_attempts - 1:
                        time.sleep(delay)
            
            # Record failure
            error_handler.record_failure(op_name)
            
            # Re-raise last exception
            if last_exception:
                raise last_exception
            else:
                raise RuntimeError("Operation failed after retries")
        
        return wrapper
    
    return decorator


# Global error handler instance
_global_error_handler: Optional[ErrorHandler] = None


def get_error_handler() -> ErrorHandler:
    """
    Get the global error handler instance.
    
    Returns:
        Global ErrorHandler instance
    """
    global _global_error_handler
    if _global_error_handler is None:
        _global_error_handler = ErrorHandler()
    return _global_error_handler
