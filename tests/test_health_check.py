"""
Unit tests for health check module.
"""

import unittest
from datetime import datetime

from aider.health_check import (
    HealthCheck,
    HealthCheckResult,
    HealthChecker,
    SystemHealth,
    get_health_checker,
    check_system_health,
)


class TestHealthCheckResult(unittest.TestCase):
    """Test health check result dataclass."""

    def test_health_check_result_creation(self):
        """Test creating a health check result."""
        result = HealthCheckResult(
            component="test_component",
            status="healthy",
            message="Test message",
            details={"key": "value"},
        )
        
        self.assertEqual(result.component, "test_component")
        self.assertEqual(result.status, "healthy")
        self.assertEqual(result.message, "Test message")


class TestSystemHealth(unittest.TestCase):
    """Test system health dataclass."""

    def test_system_health_creation(self):
        """Test creating system health."""
        health = SystemHealth(
            is_healthy=True,
            status="healthy",
            checks=[],
        )
        
        self.assertTrue(health.is_healthy)
        self.assertEqual(health.status, "healthy")


class TestHealthCheck(unittest.TestCase):
    """Test health check functionality."""

    def test_health_check_initialization(self):
        """Test health check initialization."""
        def dummy_check():
            return HealthCheckResult(
                component="test", status="healthy", message="OK"
            )
        
        check = HealthCheck("test_component", dummy_check)
        
        self.assertEqual(check.component, "test_component")
        self.assertIsNotNone(check.check_func)
    
    def test_run_health_check(self):
        """Test running a health check."""
        def dummy_check():
            return HealthCheckResult(
                component="test", status="healthy", message="OK"
            )
        
        check = HealthCheck("test_component", dummy_check)
        result = check.run()
        
        self.assertEqual(result.component, "test")
        self.assertEqual(result.status, "healthy")
    
    def test_run_health_check_with_exception(self):
        """Test running a health check that raises an exception."""
        def failing_check():
            raise ValueError("Test error")
        
        check = HealthCheck("test_component", failing_check)
        result = check.run()
        
        self.assertEqual(result.status, "unhealthy")
        self.assertIn("error", result.details)


class TestHealthChecker(unittest.TestCase):
    """Test health checker functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.checker = HealthChecker()
    
    def test_register_check(self):
        """Test registering a health check."""
        def dummy_check():
            return HealthCheckResult(
                component="custom", status="healthy", message="OK"
            )
        
        self.checker.register_check("custom", dummy_check)
        result = self.checker.check_component("custom")
        
        self.assertIsNotNone(result)
        self.assertEqual(result.component, "custom")
    
    def test_unregister_check(self):
        """Test unregistering a health check."""
        def dummy_check():
            return HealthCheckResult(
                component="custom", status="healthy", message="OK"
            )
        
        self.checker.register_check("custom", dummy_check)
        self.checker.unregister_check("custom")
        
        result = self.checker.check_component("custom")
        self.assertIsNone(result)
    
    def test_check_component(self):
        """Test checking a specific component."""
        result = self.checker.check_component("filesystem")
        
        self.assertIsNotNone(result)
        self.assertIn(result.status, ["healthy", "unhealthy"])
    
    def test_check_all(self):
        """Test checking all components."""
        health = self.checker.check_all()
        
        self.assertIsNotNone(health)
        self.assertIsNotNone(health.timestamp)
        self.assertGreater(len(health.checks), 0)
    
    def test_check_filesystem(self):
        """Test filesystem health check."""
        result = self.checker._check_filesystem()
        
        self.assertEqual(result.component, "filesystem")
        self.assertIn(result.status, ["healthy", "unhealthy"])
    
    def test_check_python_environment(self):
        """Test Python environment health check."""
        result = self.checker._check_python_environment()
        
        self.assertEqual(result.component, "python_environment")
        self.assertIn(result.status, ["healthy", "degraded", "unhealthy"])
    
    def test_check_git(self):
        """Test Git health check."""
        result = self.checker._check_git()
        
        self.assertEqual(result.component, "git")
        self.assertIn(result.status, ["healthy", "degraded", "unhealthy"])


class TestGlobalHealthChecker(unittest.TestCase):
    """Test global health checker instance."""

    def test_get_health_checker(self):
        """Test getting global health checker."""
        checker = get_health_checker()
        self.assertIsNotNone(checker)
        
        # Should return same instance
        checker2 = get_health_checker()
        self.assertIs(checker, checker2)
    
    def test_check_system_health(self):
        """Test convenience function for system health check."""
        health = check_system_health()
        
        self.assertIsNotNone(health)
        self.assertIsNotNone(health.timestamp)
        self.assertIn(health.status, ["healthy", "degraded", "unhealthy"])


if __name__ == "__main__":
    unittest.main()
