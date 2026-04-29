"""
Integration Module

This module provides integration points for the new enterprise-level features
with the existing Aider codebase. It connects the new modules with the core
functionality in a seamless manner.

Key Features:
- Integration with existing Commands class
- Integration with main.py initialization
- Configuration integration
- Health check integration
- Performance monitoring integration
- Backup/restore integration
- Notification integration
"""

from typing import Optional

from aider.logging_config import (
    AuditLogger,
    PerformanceLogger,
    setup_logging,
)
from aider.config_validator import (
    ConfigValidator,
    get_default_config,
    validate_config_file,
)
from aider.rate_limiter import RateLimiter, RateLimitPolicy, get_rate_limiter
from aider.health_check import HealthChecker, check_system_health
from aider.performance_monitor import PerformanceMonitor, get_performance_monitor
from aider.backup_restore import BackupManager, get_backup_manager
from aider.notification_system import NotificationManager, get_notification_manager
from aider.i18n import get_i18n_manager, set_language
from aider.perf_dashboard import get_performance_dashboard
from aider.error_handler import get_error_handler
from aider.api_docs import get_api_docs
from aider.feature_flags import get_feature_flag_manager, register_default_flags
from aider.session_manager import get_session_manager
from aider.code_quality_gates import get_code_quality_gates
from aider.plugin_system import get_plugin_manager
from aider.async_operations import get_async_manager


class EnterpriseFeatures:
    """
    Manager for enterprise-level features integration.
    
    This class provides a unified interface for integrating all enterprise-level
    features with the existing Aider codebase.
    """
    
    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize enterprise features.
        
        Args:
            config_path: Path to configuration file
        """
        self.config_path = config_path
        
        # Initialize components
        self._setup_logging()
        self._validate_config()
        self._setup_rate_limiting()
        self._setup_health_checking()
        self._setup_performance_monitoring()
        self._setup_backup_manager()
        self._setup_notification_manager()
        self._setup_i18n()
        self._setup_perf_dashboard()
        self._setup_error_handler()
        self._setup_api_docs()
        self._setup_feature_flags()
        self._setup_session_manager()
        self._setup_code_quality_gates()
        self._setup_plugin_system()
        self._setup_async_operations()
    
    def _setup_logging(self) -> None:
        """Setup enhanced logging."""
        setup_logging(
            log_level="INFO",
            log_dir=".aider_logs",
            enable_console=True,
            enable_json=True,
        )
        self.audit_logger = AuditLogger()
        self.performance_logger = PerformanceLogger()
    
    def _validate_config(self) -> None:
        """Validate configuration."""
        if self.config_path:
            result = validate_config_file(self.config_path)
            if not result.is_valid:
                print(f"Configuration validation failed: {len(result.errors)} errors")
                for error in result.errors:
                    print(f"  - {error.field}: {error.message}")
        else:
            # Use default config
            self.config = get_default_config()
    
    def _setup_rate_limiting(self) -> None:
        """Setup rate limiting."""
        policy = RateLimitPolicy(
            requests_per_minute=60,
            requests_per_hour=1000,
            requests_per_day=10000,
        )
        self.rate_limiter = RateLimiter(policy)
    
    def _setup_health_checking(self) -> None:
        """Setup health checking."""
        self.health_checker = HealthChecker()
    
    def _setup_performance_monitoring(self) -> None:
        """Setup performance monitoring."""
        self.performance_monitor = PerformanceMonitor()
        self.performance_monitor.start_monitoring()
    
    def _setup_backup_manager(self) -> None:
        """Setup backup manager."""
        self.backup_manager = get_backup_manager()
    
    def _setup_notification_manager(self) -> None:
        """Setup notification manager."""
        self.notification_manager = get_notification_manager()
    
    def _setup_i18n(self) -> None:
        """Setup internationalization."""
        self.i18n_manager = get_i18n_manager()
        # Set default language to English
        set_language("en")
    
    def _setup_perf_dashboard(self) -> None:
        """Setup performance dashboard."""
        self.perf_dashboard = get_performance_dashboard()
    
    def _setup_error_handler(self) -> None:
        """Setup error handler."""
        self.error_handler = get_error_handler()
    
    def _setup_api_docs(self) -> None:
        """Setup API documentation."""
        self.api_docs = get_api_docs()
    
    def _setup_feature_flags(self) -> None:
        """Setup feature flags."""
        self.feature_flags = get_feature_flag_manager()
        register_default_flags()
    
    def _setup_session_manager(self) -> None:
        """Setup session manager."""
        self.session_manager = get_session_manager()
    
    def _setup_code_quality_gates(self) -> None:
        """Setup code quality gates."""
        self.code_quality_gates = get_code_quality_gates()
    
    def _setup_plugin_system(self) -> None:
        """Setup plugin system."""
        self.plugin_manager = get_plugin_manager()
    
    def _setup_async_operations(self) -> None:
        """Setup async operations."""
        self.async_manager = get_async_manager()
    
    def get_system_health(self):
        """Get current system health status."""
        return self.health_checker.check_all()
    
    def get_performance_report(self):
        """Get performance report."""
        return self.performance_monitor.get_performance_report()
    
    def shutdown(self):
        """Shutdown enterprise features gracefully."""
        self.performance_monitor.stop_monitoring()
        self.session_manager.shutdown()
        self.async_manager.cleanup()


# Global enterprise features instance
_enterprise_features: Optional[EnterpriseFeatures] = None


def initialize_enterprise_features(config_path: Optional[str] = None) -> EnterpriseFeatures:
    """
    Initialize enterprise features.
    
    Args:
        config_path: Path to configuration file
        
    Returns:
        EnterpriseFeatures instance
    """
    global _enterprise_features
    if _enterprise_features is None:
        _enterprise_features = EnterpriseFeatures(config_path)
    return _enterprise_features


def get_enterprise_features() -> Optional[EnterpriseFeatures]:
    """
    Get the global enterprise features instance.
    
    Returns:
        EnterpriseFeatures instance or None if not initialized
    """
    return _enterprise_features
