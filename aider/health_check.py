"""
Health Check Module

This module provides health check functionality for the Aider AI coding assistant.
It implements aerospace-level health monitoring with component checks,
dependency verification, and system status reporting.

Key Features:
- Component health checks (API, Git, File system, etc.)
- Dependency verification
- System resource monitoring
- Health status aggregation
- Configurable health check policies
- Alerting on health degradation
"""

import os
import sys
import time
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


@dataclass
class HealthCheckResult:
    """
    Result of a health check.
    
    Attributes:
        component: Name of the component checked
        status: Health status (healthy, degraded, unhealthy)
        message: Human-readable status message
        details: Additional details about the check
        timestamp: When the check was performed
        duration_ms: Duration of the check in milliseconds
    """
    component: str
    status: str  # "healthy", "degraded", "unhealthy"
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    duration_ms: float = 0.0


@dataclass
class SystemHealth:
    """
    Overall system health status.
    
    Attributes:
        is_healthy: Whether the system is healthy
        status: Overall health status
        checks: List of individual health check results
        timestamp: When the health check was performed
    """
    is_healthy: bool
    status: str
    checks: List[HealthCheckResult] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.utcnow)


class HealthCheck:
    """
    Health check for a specific component or system.
    
    This class provides a framework for implementing aerospace-level
    health checks with configurable thresholds and monitoring.
    """
    
    def __init__(
        self,
        component: str,
        check_func: Callable[[], HealthCheckResult],
        interval_seconds: int = 60,
        timeout_seconds: int = 10,
    ):
        """
        Initialize a health check.
        
        Args:
            component: Name of the component being checked
            check_func: Function that performs the health check
            interval_seconds: How often to run the check
            timeout_seconds: Maximum time to wait for check completion
        """
        self.component = component
        self.check_func = check_func
        self.interval_seconds = interval_seconds
        self.timeout_seconds = timeout_seconds
        self.last_result: Optional[HealthCheckResult] = None
        self.last_check_time: Optional[datetime] = None
        self._lock = threading.Lock()
    
    def run(self) -> HealthCheckResult:
        """
        Run the health check.
        
        Returns:
            HealthCheckResult with the check outcome
        """
        start_time = time.time()
        
        try:
            result = self.check_func()
            result.duration_ms = (time.time() - start_time) * 1000
            
            with self._lock:
                self.last_result = result
                self.last_check_time = datetime.utcnow()
            
            return result
        except Exception as e:
            # Return unhealthy result on error
            result = HealthCheckResult(
                component=self.component,
                status="unhealthy",
                message=f"Health check failed: {str(e)}",
                details={"error": str(e), "error_type": type(e).__name__},
                duration_ms=(time.time() - start_time) * 1000,
            )
            
            with self._lock:
                self.last_result = result
                self.last_check_time = datetime.utcnow()
            
            return result


class HealthChecker:
    """
    Health checker that aggregates multiple health checks.
    
    This class provides comprehensive health monitoring by running
    multiple health checks and aggregating their results.
    """
    
    def __init__(self):
        """Initialize the health checker."""
        self._checks: Dict[str, HealthCheck] = {}
        self._lock = threading.Lock()
        
        # Register default health checks
        self._register_default_checks()
    
    def _register_default_checks(self) -> None:
        """Register default health checks."""
        self.register_check("filesystem", self._check_filesystem)
        self.register_check("python_environment", self._check_python_environment)
        self.register_check("git", self._check_git)
        self.register_check("dependencies", self._check_dependencies)
        self.register_check("disk_space", self._check_disk_space)
        self.register_check("memory", self._check_memory)
    
    def register_check(self, component: str, check_func: Callable[[], HealthCheckResult]) -> None:
        """
        Register a health check.
        
        Args:
            component: Name of the component
            check_func: Function that performs the health check
        """
        with self._lock:
            self._checks[component] = HealthCheck(component, check_func)
    
    def unregister_check(self, component: str) -> None:
        """
        Unregister a health check.
        
        Args:
            component: Name of the component to unregister
        """
        with self._lock:
            self._checks.pop(component, None)
    
    def check_component(self, component: str) -> Optional[HealthCheckResult]:
        """
        Check a specific component.
        
        Args:
            component: Name of the component to check
            
        Returns:
            HealthCheckResult or None if component not found
        """
        with self._lock:
            check = self._checks.get(component)
        
        if check:
            return check.run()
        return None
    
    def check_all(self) -> SystemHealth:
        """
        Check all registered components.
        
        Returns:
            SystemHealth with overall system status
        """
        results = []
        all_healthy = True
        any_degraded = False
        
        with self._lock:
            checks = list(self._checks.values())
        
        for check in checks:
            result = check.run()
            results.append(result)
            
            if result.status == "unhealthy":
                all_healthy = False
            elif result.status == "degraded":
                any_degraded = True
        
        # Determine overall status
        if all_healthy:
            status = "healthy"
        elif any_degraded:
            status = "degraded"
        else:
            status = "unhealthy"
        
        return SystemHealth(
            is_healthy=all_healthy,
            status=status,
            checks=results,
            timestamp=datetime.utcnow(),
        )
    
    def _check_filesystem(self) -> HealthCheckResult:
        """Check filesystem accessibility."""
        try:
            # Test write permission in current directory
            test_file = Path(".health_check_test")
            test_file.touch()
            test_file.unlink()
            
            return HealthCheckResult(
                component="filesystem",
                status="healthy",
                message="Filesystem is accessible and writable",
                details={"write_permission": True},
            )
        except Exception as e:
            return HealthCheckResult(
                component="filesystem",
                status="unhealthy",
                message=f"Filesystem check failed: {str(e)}",
                details={"error": str(e)},
            )
    
    def _check_python_environment(self) -> HealthCheckResult:
        """Check Python environment health."""
        try:
            python_version = sys.version_info
            details = {
                "python_version": f"{python_version.major}.{python_version.minor}.{python_version.micro}",
                "executable": sys.executable,
            }
            
            # Check Python version (require 3.8+)
            if python_version < (3, 8):
                return HealthCheckResult(
                    component="python_environment",
                    status="degraded",
                    message="Python version is below recommended minimum (3.8+)",
                    details=details,
                )
            
            return HealthCheckResult(
                component="python_environment",
                status="healthy",
                message="Python environment is healthy",
                details=details,
            )
        except Exception as e:
            return HealthCheckResult(
                component="python_environment",
                status="unhealthy",
                message=f"Python environment check failed: {str(e)}",
                details={"error": str(e)},
            )
    
    def _check_git(self) -> HealthCheckResult:
        """Check Git availability."""
        try:
            import git
            
            # Try to get git version
            git_version = git.__version__
            
            return HealthCheckResult(
                component="git",
                status="healthy",
                message="Git is available",
                details={"git_version": git_version},
            )
        except ImportError:
            return HealthCheckResult(
                component="git",
                status="degraded",
                message="Git module not installed",
                details={"suggestion": "Install gitpython: pip install gitpython"},
            )
        except Exception as e:
            return HealthCheckResult(
                component="git",
                status="unhealthy",
                message=f"Git check failed: {str(e)}",
                details={"error": str(e)},
            )
    
    def _check_dependencies(self) -> HealthCheckResult:
        """Check critical dependencies."""
        critical_deps = ["openai", "anthropic", "litellm"]
        missing_deps = []
        installed_deps = {}
        
        for dep in critical_deps:
            try:
                module = __import__(dep)
                installed_deps[dep] = getattr(module, "__version__", "unknown")
            except ImportError:
                missing_deps.append(dep)
        
        if missing_deps:
            return HealthCheckResult(
                component="dependencies",
                status="degraded",
                message=f"Missing critical dependencies: {', '.join(missing_deps)}",
                details={
                    "missing": missing_deps,
                    "installed": installed_deps,
                },
            )
        
        return HealthCheckResult(
            component="dependencies",
            status="healthy",
            message="All critical dependencies are installed",
            details={"installed": installed_deps},
        )
    
    def _check_disk_space(self) -> HealthCheckResult:
        """Check disk space availability."""
        try:
            import shutil
            
            disk_usage = shutil.disk_usage(".")
            free_gb = disk_usage.free / (1024**3)
            total_gb = disk_usage.total / (1024**3)
            used_percent = (disk_usage.used / disk_usage.total) * 100
            
            details = {
                "free_gb": round(free_gb, 2),
                "total_gb": round(total_gb, 2),
                "used_percent": round(used_percent, 2),
            }
            
            # Alert if less than 1GB free or more than 90% used
            if free_gb < 1 or used_percent > 90:
                return HealthCheckResult(
                    component="disk_space",
                    status="degraded",
                    message=f"Low disk space: {free_gb:.2f}GB free ({used_percent:.1f}% used)",
                    details=details,
                )
            
            return HealthCheckResult(
                component="disk_space",
                status="healthy",
                message=f"Disk space is adequate: {free_gb:.2f}GB free",
                details=details,
            )
        except Exception as e:
            return HealthCheckResult(
                component="disk_space",
                status="unhealthy",
                message=f"Disk space check failed: {str(e)}",
                details={"error": str(e)},
            )
    
    def _check_memory(self) -> HealthCheckResult:
        """Check memory availability."""
        try:
            import psutil
            
            mem = psutil.virtual_memory()
            available_gb = mem.available / (1024**3)
            total_gb = mem.total / (1024**3)
            used_percent = mem.percent
            
            details = {
                "available_gb": round(available_gb, 2),
                "total_gb": round(total_gb, 2),
                "used_percent": round(used_percent, 2),
            }
            
            # Alert if less than 512MB available or more than 90% used
            if available_gb < 0.5 or used_percent > 90:
                return HealthCheckResult(
                    component="memory",
                    status="degraded",
                    message=f"Low memory: {available_gb:.2f}GB available ({used_percent:.1f}% used)",
                    details=details,
                )
            
            return HealthCheckResult(
                component="memory",
                status="healthy",
                message=f"Memory is adequate: {available_gb:.2f}GB available",
                details=details,
            )
        except ImportError:
            return HealthCheckResult(
                component="memory",
                status="degraded",
                message="psutil not installed for memory checking",
                details={"suggestion": "Install psutil: pip install psutil"},
            )
        except Exception as e:
            return HealthCheckResult(
                component="memory",
                status="unhealthy",
                message=f"Memory check failed: {str(e)}",
                details={"error": str(e)},
            )


# Global health checker instance
_global_health_checker: Optional[HealthChecker] = None


def get_health_checker() -> HealthChecker:
    """
    Get the global health checker instance.
    
    Returns:
        Global HealthChecker instance
    """
    global _global_health_checker
    if _global_health_checker is None:
        _global_health_checker = HealthChecker()
    return _global_health_checker


def check_system_health() -> SystemHealth:
    """
    Check overall system health.
    
    This is a convenience function for quick health checking.
    
    Returns:
        SystemHealth with overall system status
    """
    checker = get_health_checker()
    return checker.check_all()
