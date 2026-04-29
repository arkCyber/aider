"""
Unit tests for logging configuration module.
"""

import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from aider.logging_config import (
    AuditLogger,
    PerformanceLogger,
    StructuredFormatter,
    setup_logging,
)


class TestStructuredFormatter(unittest.TestCase):
    """Test the structured JSON formatter."""

    def test_format_basic_log(self):
        """Test basic log formatting."""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            "test_logger",
            logging.INFO,
            "test_module",
            42,
            "Test message",
            (),
            None,
        )
        
        result = formatter.format(record)
        log_data = json.loads(result)
        
        self.assertEqual(log_data["level"], "INFO")
        self.assertEqual(log_data["logger"], "test_logger")
        self.assertEqual(log_data["message"], "Test message")
        self.assertIn("timestamp", log_data)


class TestPerformanceLogger(unittest.TestCase):
    """Test the performance logger."""

    def setUp(self):
        """Set up test fixtures."""
        self.logger = PerformanceLogger()
    
    def test_start_end_timer(self):
        """Test starting and ending a timer."""
        self.logger.start_timer("test_operation")
        duration = self.logger.end_timer("test_operation")
        
        self.assertIsNotNone(duration)
        self.assertGreaterEqual(duration, 0)
    
    def test_timer_not_found(self):
        """Test ending a non-existent timer."""
        duration = self.logger.end_timer("nonexistent_operation")
        self.assertIsNone(duration)
    
    def test_concurrent_timers(self):
        """Test multiple concurrent timers."""
        self.logger.start_timer("op1")
        self.logger.start_timer("op2")
        
        duration1 = self.logger.end_timer("op1")
        duration2 = self.logger.end_timer("op2")
        
        self.assertIsNotNone(duration1)
        self.assertIsNotNone(duration2)


class TestAuditLogger(unittest.TestCase):
    """Test the audit logger."""

    def setUp(self):
        """Set up test fixtures."""
        self.logger = AuditLogger()
    
    def test_log_command_start(self):
        """Test logging command start."""
        # This should not raise an exception
        self.logger.log_command_start("test_command", "arg1 arg2", "test_user")
    
    def test_log_command_end(self):
        """Test logging command end."""
        # This should not raise an exception
        self.logger.log_command_end("test_command", "success", "details")
    
    def test_log_security_event(self):
        """Test logging security event."""
        # This should not raise an exception
        self.logger.log_security_event("test_event", "event details", "warning")


class TestSetupLogging(unittest.TestCase):
    """Test logging setup."""

    def test_setup_logging(self):
        """Test logging setup with temp directory."""
        with tempfile.TemporaryDirectory() as temp_dir:
            setup_logging(log_dir=temp_dir, enable_console=False)
            
            # Check that log files were created
            log_path = Path(temp_dir)
            self.assertTrue((log_path / "aider.log").exists())
            self.assertTrue((log_path / "aider_structured.log").exists())
            self.assertTrue((log_path / "aider_audit.log").exists())
            self.assertTrue((log_path / "aider_performance.log").exists())


if __name__ == "__main__":
    unittest.main()
