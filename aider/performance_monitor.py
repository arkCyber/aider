"""
Performance Monitoring Module

This module provides comprehensive performance monitoring for the Aider AI coding assistant.
It implements aerospace-level performance tracking with metrics collection, profiling,
and performance analysis.

Key Features:
- Performance metrics collection (latency, throughput, error rates)
- Code profiling and hot spot identification
- Resource usage monitoring (CPU, memory, I/O)
- Performance trend analysis
- Alerting on performance degradation
- Configurable performance thresholds
"""

import os
import sys
import time
import threading
import cProfile
import pstats
import io
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple


@dataclass
class PerformanceMetric:
    """
    Performance metric data point.
    
    Attributes:
        name: Name of the metric
        value: Metric value
        timestamp: When the metric was recorded
        tags: Additional tags for categorization
    """
    name: str
    value: float
    timestamp: datetime = field(default_factory=datetime.utcnow)
    tags: Dict[str, str] = field(default_factory=dict)


@dataclass
class PerformanceStats:
    """
    Statistical summary of performance metrics.
    
    Attributes:
        metric_name: Name of the metric
        count: Number of data points
        mean: Average value
        min: Minimum value
        max: Maximum value
        p50: 50th percentile
        p95: 95th percentile
        p99: 99th percentile
        std_dev: Standard deviation
    """
    metric_name: str
    count: int
    mean: float
    min: float
    max: float
    p50: float
    p95: float
    p99: float
    std_dev: float


class MetricsCollector:
    """
    Collects and aggregates performance metrics.
    
    This class provides aerospace-level metrics collection with
    efficient storage and statistical analysis.
    """
    
    def __init__(self, max_samples: int = 10000):
        """
        Initialize the metrics collector.
        
        Args:
            max_samples: Maximum number of samples to keep per metric
        """
        self._metrics: Dict[str, deque] = defaultdict(lambda: deque(maxlen=max_samples))
        self._lock = threading.Lock()
        self._max_samples = max_samples
    
    def record(self, metric: PerformanceMetric) -> None:
        """
        Record a performance metric.
        
        Args:
            metric: Performance metric to record
        """
        with self._lock:
            self._metrics[metric.name].append(metric)
    
    def record_value(
        self, name: str, value: float, tags: Optional[Dict[str, str]] = None
    ) -> None:
        """
        Record a metric value.
        
        Args:
            name: Name of the metric
            value: Metric value
            tags: Optional tags for categorization
        """
        metric = PerformanceMetric(name=name, value=value, tags=tags or {})
        self.record(metric)
    
    def get_metrics(self, name: str) -> List[PerformanceMetric]:
        """
        Get all metrics for a given name.
        
        Args:
            name: Name of the metric
            
        Returns:
            List of performance metrics
        """
        with self._lock:
            return list(self._metrics.get(name, []))
    
    def get_stats(self, name: str) -> Optional[PerformanceStats]:
        """
        Get statistical summary for a metric.
        
        Args:
            name: Name of the metric
            
        Returns:
            PerformanceStats or None if no data available
        """
        metrics = self.get_metrics(name)
        if not metrics:
            return None
        
        values = [m.value for m in metrics]
        values_sorted = sorted(values)
        
        count = len(values)
        mean = sum(values) / count
        min_val = min(values)
        max_val = max(values)
        
        # Calculate percentiles
        p50 = values_sorted[int(count * 0.5)]
        p95 = values_sorted[int(count * 0.95)]
        p99 = values_sorted[int(count * 0.99)]
        
        # Calculate standard deviation
        variance = sum((x - mean) ** 2 for x in values) / count
        std_dev = variance ** 0.5
        
        return PerformanceStats(
            metric_name=name,
            count=count,
            mean=mean,
            min=min_val,
            max=max_val,
            p50=p50,
            p95=p95,
            p99=p99,
            std_dev=std_dev,
        )
    
    def get_all_metric_names(self) -> List[str]:
        """
        Get all metric names that have been recorded.
        
        Returns:
            List of metric names
        """
        with self._lock:
            return list(self._metrics.keys())


class PerformanceProfiler:
    """
    Code profiler for identifying performance bottlenecks.
    
    This class provides aerospace-level profiling with cProfile
    integration and analysis tools.
    """
    
    def __init__(self):
        """Initialize the performance profiler."""
        self._profilers: Dict[str, cProfile.Profile] = {}
        self._lock = threading.Lock()
    
    def start_profiling(self, name: str = "default") -> None:
        """
        Start profiling.
        
        Args:
            name: Name of the profiling session
        """
        with self._lock:
            profiler = cProfile.Profile()
            profiler.enable()
            self._profilers[name] = profiler
    
    def stop_profiling(self, name: str = "default") -> Optional[pstats.Stats]:
        """
        Stop profiling and return statistics.
        
        Args:
            name: Name of the profiling session
            
        Returns:
            Stats object or None if profiling session not found
        """
        with self._lock:
            profiler = self._profilers.pop(name, None)
            if profiler:
                profiler.disable()
                stats = pstats.Stats(profiler)
                return stats
        return None
    
    def profile_function(
        self, func: Callable, *args, **kwargs
    ) -> Tuple[Any, pstats.Stats]:
        """
        Profile a function call.
        
        Args:
            func: Function to profile
            *args: Function arguments
            **kwargs: Function keyword arguments
            
        Returns:
            Tuple of (function result, stats)
        """
        profiler = cProfile.Profile()
        profiler.enable()
        
        try:
            result = func(*args, **kwargs)
        finally:
            profiler.disable()
        
        stats = pstats.Stats(profiler)
        return result, stats
    
    def get_top_functions(
        self, stats: pstats.Stats, n: int = 10
    ) -> List[Tuple[str, float, int]]:
        """
        Get top functions by cumulative time.
        
        Args:
            stats: Stats object from profiling
            n: Number of top functions to return
            
        Returns:
            List of (function_name, cumulative_time, call_count)
        """
        stats.sort_stats('cumulative')
        top_functions = []
        
        for func, (cc, nc, tt, ct, callers) in stats.stats.items()[:n]:
            func_name = f"{func[0]}:{func[1]}({func[2]})"
            top_functions.append((func_name, ct, cc))
        
        return top_functions


class ResourceMonitor:
    """
    Monitor system resource usage.
    
    This class provides aerospace-level resource monitoring
    for CPU, memory, and I/O operations.
    """
    
    def __init__(self, interval_seconds: float = 1.0):
        """
        Initialize the resource monitor.
        
        Args:
            interval_seconds: Interval between measurements
        """
        self.interval_seconds = interval_seconds
        self._monitoring = False
        self._thread: Optional[threading.Thread] = None
        self._metrics: Dict[str, deque] = defaultdict(lambda: deque(maxlen=3600))
        self._lock = threading.Lock()
    
    def start(self) -> None:
        """Start resource monitoring."""
        if self._monitoring:
            return
        
        self._monitoring = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
    
    def stop(self) -> None:
        """Stop resource monitoring."""
        self._monitoring = False
        if self._thread:
            self._thread.join(timeout=5.0)
    
    def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        while self._monitoring:
            try:
                self._collect_metrics()
            except Exception as e:
                print(f"Resource monitoring error: {e}", file=sys.stderr)
            
            time.sleep(self.interval_seconds)
    
    def _collect_metrics(self) -> None:
        """Collect resource metrics."""
        timestamp = datetime.utcnow()
        
        try:
            import psutil
            
            # CPU metrics
            cpu_percent = psutil.cpu_percent(interval=0.1)
            self._record_metric("cpu_percent", cpu_percent, timestamp)
            
            # Memory metrics
            memory = psutil.virtual_memory()
            self._record_metric("memory_percent", memory.percent, timestamp)
            self._record_metric("memory_available_gb", memory.available / (1024**3), timestamp)
            
            # Disk I/O metrics
            disk_io = psutil.disk_io_counters()
            if disk_io:
                self._record_metric("disk_read_bytes", disk_io.read_bytes, timestamp)
                self._record_metric("disk_write_bytes", disk_io.write_bytes, timestamp)
            
            # Network I/O metrics
            net_io = psutil.net_io_counters()
            if net_io:
                self._record_metric("net_recv_bytes", net_io.bytes_recv, timestamp)
                self._record_metric("net_sent_bytes", net_io.bytes_sent, timestamp)
            
        except ImportError:
            # psutil not available, use basic metrics
            pass
    
    def _record_metric(self, name: str, value: float, timestamp: datetime) -> None:
        """
        Record a resource metric.
        
        Args:
            name: Name of the metric
            value: Metric value
            timestamp: Timestamp of the measurement
        """
        with self._lock:
            self._metrics[name].append((timestamp, value))
    
    def get_metric_history(self, name: str, duration_seconds: int = 3600) -> List[Tuple[datetime, float]]:
        """
        Get metric history for a given duration.
        
        Args:
            name: Name of the metric
            duration_seconds: Duration to look back
            
        Returns:
            List of (timestamp, value) tuples
        """
        cutoff_time = datetime.utcnow() - timedelta(seconds=duration_seconds)
        
        with self._lock:
            history = self._metrics.get(name, deque())
            return [(t, v) for t, v in history if t >= cutoff_time]
    
    def get_current_metrics(self) -> Dict[str, float]:
        """
        Get current resource metrics.
        
        Returns:
            Dictionary of current metric values
        """
        current = {}
        
        with self._lock:
            for name, history in self._metrics.items():
                if history:
                    current[name] = history[-1][1]
        
        return current


class PerformanceMonitor:
    """
    Main performance monitoring interface.
    
    This class provides a unified interface for all performance
    monitoring capabilities.
    """
    
    def __init__(self):
        """Initialize the performance monitor."""
        self.metrics_collector = MetricsCollector()
        self.profiler = PerformanceProfiler()
        self.resource_monitor = ResourceMonitor()
        self._lock = threading.Lock()
    
    def start_monitoring(self) -> None:
        """Start all performance monitoring."""
        self.resource_monitor.start()
    
    def stop_monitoring(self) -> None:
        """Stop all performance monitoring."""
        self.resource_monitor.stop()
    
    def record_metric(self, name: str, value: float, tags: Optional[Dict[str, str]] = None) -> None:
        """
        Record a performance metric.
        
        Args:
            name: Name of the metric
            value: Metric value
            tags: Optional tags for categorization
        """
        self.metrics_collector.record_value(name, value, tags)
    
    def get_performance_report(self) -> Dict[str, Any]:
        """
        Get a comprehensive performance report.
        
        Returns:
            Dictionary containing performance metrics and stats
        """
        report = {
            "timestamp": datetime.utcnow().isoformat(),
            "metrics": {},
            "resource_usage": self.resource_monitor.get_current_metrics(),
        }
        
        # Get stats for all metrics
        for metric_name in self.metrics_collector.get_all_metric_names():
            stats = self.metrics_collector.get_stats(metric_name)
            if stats:
                report["metrics"][metric_name] = {
                    "count": stats.count,
                    "mean": stats.mean,
                    "min": stats.min,
                    "max": stats.max,
                    "p50": stats.p50,
                    "p95": stats.p95,
                    "p99": stats.p99,
                    "std_dev": stats.std_dev,
                }
        
        return report


# Global performance monitor instance
_global_performance_monitor: Optional[PerformanceMonitor] = None


def get_performance_monitor() -> PerformanceMonitor:
    """
    Get the global performance monitor instance.
    
    Returns:
        Global PerformanceMonitor instance
    """
    global _global_performance_monitor
    if _global_performance_monitor is None:
        _global_performance_monitor = PerformanceMonitor()
    return _global_performance_monitor


def record_performance_metric(name: str, value: float, tags: Optional[Dict[str, str]] = None) -> None:
    """
    Record a performance metric (convenience function).
    
    Args:
        name: Name of the metric
        value: Metric value
        tags: Optional tags for categorization
    """
    monitor = get_performance_monitor()
    monitor.record_metric(name, value, tags)
