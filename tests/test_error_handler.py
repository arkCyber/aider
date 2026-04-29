"""
Unit tests for error handler module.
"""

import unittest
from datetime import datetime

from aider.error_handler import (
    ErrorCategory,
    ErrorContext,
    ErrorSeverity,
    ErrorHandler,
    RecoveryStrategy,
    RetryConfig,
    with_retry,
    get_error_handler,
)


class TestErrorCategory(unittest.TestCase):
    """Test error category enum."""

    def test_error_category_values(self):
        """Test error category enum values."""
        self.assertEqual(ErrorCategory.NETWORK.value, "network")
        self.assertEqual(ErrorCategory.API.value, "api")
        self.assertEqual(ErrorCategory.FILESYSTEM.value, "filesystem")


class TestErrorSeverity(unittest.TestCase):
    """Test error severity enum."""

    def test_error_severity_values(self):
        """Test error severity enum values."""
        self.assertEqual(ErrorSeverity.LOW.value, "low")
        self.assertEqual(ErrorSeverity.HIGH.value, "high")
        self.assertEqual(ErrorSeverity.CRITICAL.value, "critical")


class TestRecoveryStrategy(unittest.TestCase):
    """Test recovery strategy enum."""

    def test_recovery_strategy_values(self):
        """Test recovery strategy enum values."""
        self.assertEqual(RecoveryStrategy.RETRY.value, "retry")
        self.assertEqual(RecoveryStrategy.FALLBACK.value, "fallback")
        self.assertEqual(RecoveryStrategy.ABORT.value, "abort")


class TestErrorContext(unittest.TestCase):
    """Test error context dataclass."""

    def test_error_context_creation(self):
        """Test creating an error context."""
        context = ErrorContext(
            error_type=ValueError,
            error_message="Test error",
            error_category=ErrorCategory.VALIDATION,
            severity=ErrorSeverity.MEDIUM,
        )
        
        self.assertEqual(context.error_type, ValueError)
        self.assertEqual(context.error_message, "Test error")
        self.assertEqual(context.error_category, ErrorCategory.VALIDATION)


class TestRetryConfig(unittest.TestCase):
    """Test retry configuration dataclass."""

    def test_retry_config_creation(self):
        """Test creating retry configuration."""
        config = RetryConfig(
            max_attempts=5,
            base_delay=2.0,
            exponential_backoff=True,
        )
        
        self.assertEqual(config.max_attempts, 5)
        self.assertEqual(config.base_delay, 2.0)
        self.assertTrue(config.exponential_backoff)


class TestErrorHandler(unittest.TestCase):
    """Test error handler functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.handler = ErrorHandler()
    
    def test_classify_error(self):
        """Test error classification."""
        error = ValueError("Test error")
        context = self.handler.classify_error(error)
        
        self.assertIsNotNone(context)
        self.assertEqual(context.error_type, ValueError)
    
    def test_classify_network_error(self):
        """Test classifying network error."""
        error = ConnectionError("Network error")
        context = self.handler.classify_error(error)
        
        self.assertEqual(context.error_category, ErrorCategory.NETWORK)
    
    def test_handle_error(self):
        """Test error handling."""
        error = ValueError("Test error")
        context = self.handler.handle_error(error)
        
        self.assertIsNotNone(context)
        self.assertEqual(context.error_type, ValueError)
    
    def test_circuit_breaker(self):
        """Test circuit breaker functionality."""
        # Initially closed
        self.assertTrue(self.handler.check_circuit_breaker("test_operation"))
        
        # Record failures
        for _ in range(5):
            self.handler.record_failure("test_operation")
        
        # Should be open
        self.assertFalse(self.handler.check_circuit_breaker("test_operation"))
        
        # Record success
        self.handler.record_success("test_operation")
        
        # Should be closed again
        self.assertTrue(self.handler.check_circuit_breaker("test_operation"))
    
    def test_get_error_statistics(self):
        """Test getting error statistics."""
        error = ValueError("Test error")
        self.handler.handle_error(error)
        
        stats = self.handler.get_error_statistics()
        
        self.assertIn("total_errors", stats)
        self.assertGreater(stats["total_errors"], 0)


class TestWithRetryDecorator(unittest.TestCase):
    """Test the with_retry decorator."""

    def test_successful_operation(self):
        """Test successful operation with retry."""
        @with_retry()
        def test_func():
            return 42
        
        result = test_func()
        self.assertEqual(result, 42)
    
    def test_retry_on_failure(self):
        """Test retry on failure."""
        attempt_count = [0]
        
        @with_retry(config=RetryConfig(max_attempts=3))
        def test_func():
            attempt_count[0] += 1
            if attempt_count[0] < 2:
                raise ValueError("Test error")
            return 42
        
        result = test_func()
        self.assertEqual(result, 42)
        self.assertEqual(attempt_count[0], 2)
    
    def test_max_attempts_exceeded(self):
        """Test max attempts exceeded."""
        @with_retry(config=RetryConfig(max_attempts=3))
        def test_func():
            raise ValueError("Test error")
        
        with self.assertRaises(ValueError):
            test_func()


class TestGlobalErrorHandler(unittest.TestCase):
    """Test global error handler instance."""

    def test_get_error_handler(self):
        """Test getting global error handler."""
        handler = get_error_handler()
        self.assertIsNotNone(handler)
        
        # Should return same instance
        handler2 = get_error_handler()
        self.assertIs(handler, handler2)


if __name__ == "__main__":
    unittest.main()
