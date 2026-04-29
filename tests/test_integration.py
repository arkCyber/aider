"""
Integration tests for enterprise features.

These tests verify that the enterprise features integrate properly
with each other and with the existing Aider codebase.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from aider.integration import (
    EnterpriseFeatures,
    initialize_enterprise_features,
    get_enterprise_features,
)


class TestEnterpriseFeatures(unittest.TestCase):
    """Test enterprise features integration."""

    def test_initialization(self):
        """Test enterprise features initialization."""
        features = EnterpriseFeatures()
        
        # Verify all components are initialized
        self.assertIsNotNone(features.audit_logger)
        self.assertIsNotNone(features.performance_logger)
        self.assertIsNotNone(features.rate_limiter)
        self.assertIsNotNone(features.health_checker)
        self.assertIsNotNone(features.performance_monitor)
        self.assertIsNotNone(features.backup_manager)
        self.assertIsNotNone(features.notification_manager)
        self.assertIsNotNone(features.i18n_manager)
        self.assertIsNotNone(features.perf_dashboard)
        self.assertIsNotNone(features.error_handler)
        self.assertIsNotNone(features.api_docs)
        self.assertIsNotNone(features.feature_flags)
        self.assertIsNotNone(features.session_manager)
        self.assertIsNotNone(features.code_quality_gates)
        self.assertIsNotNone(features.plugin_manager)
        self.assertIsNotNone(features.async_manager)
    
    def test_get_system_health(self):
        """Test getting system health."""
        features = EnterpriseFeatures()
        health = features.get_system_health()
        
        self.assertIsNotNone(health)
    
    def test_get_performance_report(self):
        """Test getting performance report."""
        features = EnterpriseFeatures()
        report = features.get_performance_report()
        
        self.assertIsNotNone(report)
    
    def test_shutdown(self):
        """Test graceful shutdown."""
        features = EnterpriseFeatures()
        
        # Should not raise an error
        features.shutdown()


class TestGlobalEnterpriseFeatures(unittest.TestCase):
    """Test global enterprise features instance."""

    def test_initialize_enterprise_features(self):
        """Test initializing global enterprise features."""
        features = initialize_enterprise_features()
        
        self.assertIsNotNone(features)
        self.assertIsInstance(features, EnterpriseFeatures)
    
    def test_get_enterprise_features(self):
        """Test getting global enterprise features."""
        # Initialize first
        initialize_enterprise_features()
        
        # Get instance
        features = get_enterprise_features()
        
        self.assertIsNotNone(features)
    
    def test_singleton_pattern(self):
        """Test that enterprise features follows singleton pattern."""
        features1 = initialize_enterprise_features()
        features2 = get_enterprise_features()
        
        # Should return the same instance
        self.assertIs(features1, features2)


class TestFeatureIntegration(unittest.TestCase):
    """Test integration between different features."""

    def test_error_handler_with_i18n(self):
        """Test error handler integration with i18n."""
        from aider.error_handler import get_error_handler
        from aider.i18n import set_language
        
        # Set language
        set_language("en")
        
        # Get error handler
        handler = get_error_handler()
        
        # Handle an error
        try:
            raise ValueError("Test error")
        except Exception as e:
            context = handler.handle_error(e)
            
            self.assertIsNotNone(context)
    
    def test_performance_dashboard_with_monitoring(self):
        """Test performance dashboard integration with monitoring."""
        from aider.perf_dashboard import get_performance_dashboard
        from aider.performance_monitor import get_performance_monitor
        
        dashboard = get_performance_dashboard()
        monitor = get_performance_monitor()
        
        # Record a metric
        dashboard.record_metric("test_metric", 100.0)
        
        # Verify metric was recorded
        metrics = dashboard.get_metrics("test_metric")
        self.assertGreater(len(metrics), 0)
    
    def test_session_manager_with_feature_flags(self):
        """Test session manager integration with feature flags."""
        from aider.session_manager import get_session_manager
        from aider.feature_flags import get_feature_flag_manager
        
        session_manager = get_session_manager()
        feature_manager = get_feature_flag_manager()
        
        # Create a session
        session = session_manager.create_session("user123")
        
        # Check a feature flag
        enabled = feature_manager.is_enabled("enhanced_context", user_id="user123")
        
        self.assertIsNotNone(session)
        self.assertIsInstance(enabled, bool)


if __name__ == "__main__":
    unittest.main()
