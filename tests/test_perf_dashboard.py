"""
Unit tests for performance dashboard module.
"""

import time
import unittest

from aider.perf_dashboard import (
    BenchmarkResult,
    PerformanceAlert,
    PerformanceBenchmark,
    PerformanceDashboard,
    get_performance_dashboard,
)


class TestBenchmarkResult(unittest.TestCase):
    """Test benchmark result dataclass."""

    def test_benchmark_result_creation(self):
        """Test creating a benchmark result."""
        result = BenchmarkResult(
            name="test_benchmark",
            duration_ms=100.5,
            success=True,
        )
        
        self.assertEqual(result.name, "test_benchmark")
        self.assertEqual(result.duration_ms, 100.5)
        self.assertTrue(result.success)


class TestPerformanceAlert(unittest.TestCase):
    """Test performance alert dataclass."""

    def test_performance_alert_creation(self):
        """Test creating a performance alert."""
        alert = PerformanceAlert(
            metric_name="latency",
            current_value=200.0,
            threshold_value=100.0,
            severity="warning",
        )
        
        self.assertEqual(alert.metric_name, "latency")
        self.assertEqual(alert.current_value, 200.0)


class TestPerformanceBenchmark(unittest.TestCase):
    """Test performance benchmark system."""

    def setUp(self):
        """Set up test fixtures."""
        self.benchmark = PerformanceBenchmark()
    
    def test_register_threshold(self):
        """Test registering performance thresholds."""
        self.benchmark.register_threshold("latency", warning=100, critical=200)
        
        self.assertIn("latency", self.benchmark._thresholds)
        self.assertEqual(self.benchmark._thresholds["latency"]["warning"], 100)
    
    def test_run_benchmark(self):
        """Test running a benchmark."""
        def test_func():
            time.sleep(0.01)
        
        result = self.benchmark.run_benchmark("test", test_func, iterations=5)
        
        self.assertTrue(result.success)
        self.assertGreater(result.duration_ms, 0)
        self.assertEqual(result.name, "test")
    
    def test_run_benchmark_with_error(self):
        """Test running a benchmark that raises an error."""
        def failing_func():
            raise ValueError("Test error")
        
        result = self.benchmark.run_benchmark("test", failing_func)
        
        self.assertFalse(result.success)
        self.assertIsNotNone(result.error)
    
    def test_get_benchmark_history(self):
        """Test getting benchmark history."""
        def test_func():
            time.sleep(0.01)
        
        self.benchmark.run_benchmark("test", test_func)
        self.benchmark.run_benchmark("test", test_func)
        
        history = self.benchmark.get_benchmark_history("test")
        
        self.assertEqual(len(history), 2)
    
    def test_check_thresholds(self):
        """Test checking performance thresholds."""
        self.benchmark.register_threshold("latency", warning=100, critical=200)
        
        # No alert when below threshold
        alert = self.benchmark.check_thresholds("latency", 50)
        self.assertIsNone(alert)
        
        # Warning when above warning threshold
        alert = self.benchmark.check_thresholds("latency", 150)
        self.assertIsNotNone(alert)
        self.assertEqual(alert.severity, "warning")
        
        # Critical when above critical threshold
        alert = self.benchmark.check_thresholds("latency", 250)
        self.assertIsNotNone(alert)
        self.assertEqual(alert.severity, "critical")


class TestPerformanceDashboard(unittest.TestCase):
    """Test performance dashboard."""

    def setUp(self):
        """Set up test fixtures."""
        self.dashboard = PerformanceDashboard()
    
    def test_record_metric(self):
        """Test recording a metric."""
        self.dashboard.record_metric("test_metric", 100.0)
        
        metrics = self.dashboard.get_metrics("test_metric")
        self.assertEqual(len(metrics), 1)
    
    def test_get_metric_stats(self):
        """Test getting metric statistics."""
        for i in range(10):
            self.dashboard.record_metric("test", float(i * 10))
        
        stats = self.dashboard.get_metric_stats("test")
        
        self.assertIsNotNone(stats)
        self.assertEqual(stats["count"], 10)
    
    def test_get_alerts(self):
        """Test getting performance alerts."""
        self.dashboard.benchmark.register_threshold("latency", warning=100, critical=200)
        self.dashboard.record_metric("latency", 250)
        
        alerts = self.dashboard.get_alerts()
        
        self.assertGreater(len(alerts), 0)
    
    def test_generate_report(self):
        """Test generating performance report."""
        self.dashboard.record_metric("test", 100.0)
        
        report = self.dashboard.generate_report()
        
        self.assertIsNotNone(report)
        self.assertIn("timestamp", report)
        self.assertIn("metrics", report)


class TestGlobalPerformanceDashboard(unittest.TestCase):
    """Test global performance dashboard instance."""

    def test_get_performance_dashboard(self):
        """Test getting global performance dashboard."""
        dashboard = get_performance_dashboard()
        self.assertIsNotNone(dashboard)
        
        # Should return same instance
        dashboard2 = get_performance_dashboard()
        self.assertIs(dashboard, dashboard2)


if __name__ == "__main__":
    unittest.main()
