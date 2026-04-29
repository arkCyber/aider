"""
Unit tests for performance monitoring module.
"""

import time
import unittest

from aider.performance_monitor import (
    MetricsCollector,
    PerformanceMetric,
    PerformanceMonitor,
    PerformanceProfiler,
    PerformanceStats,
    ResourceMonitor,
    get_performance_monitor,
    record_performance_metric,
)


class TestPerformanceMetric(unittest.TestCase):
    """Test performance metric dataclass."""

    def test_performance_metric_creation(self):
        """Test creating a performance metric."""
        metric = PerformanceMetric(
            name="test_metric",
            value=42.5,
            tags={"key": "value"},
        )
        
        self.assertEqual(metric.name, "test_metric")
        self.assertEqual(metric.value, 42.5)
        self.assertEqual(metric.tags["key"], "value")


class TestMetricsCollector(unittest.TestCase):
    """Test metrics collector functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.collector = MetricsCollector(max_samples=100)
    
    def test_record_metric(self):
        """Test recording a metric."""
        metric = PerformanceMetric(name="test", value=1.0)
        self.collector.record(metric)
        
        metrics = self.collector.get_metrics("test")
        self.assertEqual(len(metrics), 1)
    
    def test_record_value(self):
        """Test recording a metric value."""
        self.collector.record_value("test", 1.0)
        
        metrics = self.collector.get_metrics("test")
        self.assertEqual(len(metrics), 1)
    
    def test_get_metrics(self):
        """Test getting metrics."""
        self.collector.record_value("test", 1.0)
        self.collector.record_value("test", 2.0)
        
        metrics = self.collector.get_metrics("test")
        self.assertEqual(len(metrics), 2)
    
    def test_get_stats(self):
        """Test getting statistics."""
        for i in range(10):
            self.collector.record_value("test", float(i))
        
        stats = self.collector.get_stats("test")
        
        self.assertIsNotNone(stats)
        self.assertEqual(stats.count, 10)
        self.assertEqual(stats.min, 0.0)
        self.assertEqual(stats.max, 9.0)
    
    def test_get_all_metric_names(self):
        """Test getting all metric names."""
        self.collector.record_value("metric1", 1.0)
        self.collector.record_value("metric2", 2.0)
        
        names = self.collector.get_all_metric_names()
        
        self.assertIn("metric1", names)
        self.assertIn("metric2", names)


class TestPerformanceProfiler(unittest.TestCase):
    """Test performance profiler functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.profiler = PerformanceProfiler()
    
    def test_start_stop_profiling(self):
        """Test starting and stopping profiling."""
        self.profiler.start_profiling("test")
        stats = self.profiler.stop_profiling("test")
        
        self.assertIsNotNone(stats)
    
    def test_profile_function(self):
        """Test profiling a function."""
        def test_func():
            time.sleep(0.01)
            return 42
        
        result, stats = self.profiler.profile_function(test_func)
        
        self.assertEqual(result, 42)
        self.assertIsNotNone(stats)
    
    def test_get_top_functions(self):
        """Test getting top functions."""
        def test_func():
            time.sleep(0.01)
            return 42
        
        _, stats = self.profiler.profile_function(test_func)
        top_functions = self.profiler.get_top_functions(stats, n=5)
        
        self.assertIsInstance(top_functions, list)


class TestPerformanceMonitor(unittest.TestCase):
    """Test performance monitor functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.monitor = PerformanceMonitor()
    
    def test_record_metric(self):
        """Test recording a metric."""
        self.monitor.record_metric("test", 1.0)
        
        stats = self.monitor.metrics_collector.get_stats("test")
        self.assertIsNotNone(stats)
    
    def test_get_performance_report(self):
        """Test getting performance report."""
        self.monitor.record_metric("test", 1.0)
        self.monitor.record_metric("test", 2.0)
        
        report = self.monitor.get_performance_report()
        
        self.assertIsNotNone(report)
        self.assertIn("timestamp", report)
        self.assertIn("metrics", report)
        self.assertIn("resource_usage", report)


class TestGlobalPerformanceMonitor(unittest.TestCase):
    """Test global performance monitor instance."""

    def test_get_performance_monitor(self):
        """Test getting global performance monitor."""
        monitor = get_performance_monitor()
        self.assertIsNotNone(monitor)
        
        # Should return same instance
        monitor2 = get_performance_monitor()
        self.assertIs(monitor, monitor2)
    
    def test_record_performance_metric(self):
        """Test convenience function for recording metrics."""
        record_performance_metric("test", 1.0)
        
        monitor = get_performance_monitor()
        stats = monitor.metrics_collector.get_stats("test")
        self.assertIsNotNone(stats)


if __name__ == "__main__":
    unittest.main()
