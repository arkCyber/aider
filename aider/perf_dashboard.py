"""
Performance Monitoring Dashboard Module

This module provides a performance monitoring dashboard with real-time metrics,
visualization, and benchmarking capabilities for the Aider AI coding assistant.
It implements aerospace-level performance monitoring with comprehensive analysis tools.

Key Features:
- Real-time performance metrics dashboard
- Performance benchmarking and comparison
- Historical performance data analysis
- Performance anomaly detection
- Performance trend visualization
- Automated performance reporting
"""

import json
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
import statistics


@dataclass
class BenchmarkResult:
    """
    Result of a performance benchmark.
    
    Attributes:
        name: Benchmark name
        duration_ms: Duration in milliseconds
        timestamp: When the benchmark was run
        metadata: Additional benchmark metadata
        success: Whether the benchmark completed successfully
        error: Error message if benchmark failed
    """
    name: str
    duration_ms: float
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)
    success: bool = True
    error: Optional[str] = None


@dataclass
class PerformanceAlert:
    """
    Performance alert for threshold violations.
    
    Attributes:
        metric_name: Name of the metric
        current_value: Current metric value
        threshold_value: Threshold value
        severity: Alert severity (warning, critical)
        timestamp: When the alert was triggered
        message: Alert message
    """
    metric_name: str
    current_value: float
    threshold_value: float
    severity: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    message: str = ""


class PerformanceBenchmark:
    """
    Performance benchmarking system.
    
    This class provides aerospace-level benchmarking with
    statistical analysis, comparison, and trend tracking.
    """
    
    def __init__(self):
        """Initialize the performance benchmark system."""
        self._benchmarks: Dict[str, List[BenchmarkResult]] = defaultdict(list)
        self._thresholds: Dict[str, Dict[str, float]] = {}
    
    def register_threshold(self, metric_name: str, warning: float, critical: float) -> None:
        """
        Register performance thresholds for a metric.
        
        Args:
            metric_name: Name of the metric
            warning: Warning threshold
            critical: Critical threshold
        """
        self._thresholds[metric_name] = {
            "warning": warning,
            "critical": critical,
        }
    
    def run_benchmark(
        self,
        name: str,
        func: Callable,
        iterations: int = 10,
        warmup: int = 2,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> BenchmarkResult:
        """
        Run a performance benchmark.
        
        Args:
            name: Benchmark name
            func: Function to benchmark
            iterations: Number of iterations to run
            warmup: Number of warmup iterations
            metadata: Additional metadata
            
        Returns:
            BenchmarkResult with benchmark statistics
        """
        durations = []
        
        # Warmup iterations
        for _ in range(warmup):
            try:
                func()
            except Exception:
                pass
        
        # Benchmark iterations
        for _ in range(iterations):
            try:
                start = time.perf_counter()
                func()
                duration = time.perf_counter() - start
                durations.append(duration * 1000)  # Convert to milliseconds
            except Exception as e:
                return BenchmarkResult(
                    name=name,
                    duration_ms=0,
                    success=False,
                    error=str(e),
                    metadata=metadata or {},
                )
        
        if not durations:
            return BenchmarkResult(
                name=name,
                duration_ms=0,
                success=False,
                error="No successful iterations",
                metadata=metadata or {},
            )
        
        # Calculate statistics
        mean_duration = statistics.mean(durations)
        median_duration = statistics.median(durations)
        std_duration = statistics.stdev(durations) if len(durations) > 1 else 0
        min_duration = min(durations)
        max_duration = max(durations)
        
        result = BenchmarkResult(
            name=name,
            duration_ms=mean_duration,
            metadata={
                **(metadata or {}),
                "iterations": iterations,
                "mean_ms": mean_duration,
                "median_ms": median_duration,
                "std_ms": std_duration,
                "min_ms": min_duration,
                "max_ms": max_duration,
            },
        )
        
        self._benchmarks[name].append(result)
        
        return result
    
    def get_benchmark_history(self, name: str, limit: int = 100) -> List[BenchmarkResult]:
        """
        Get benchmark history for a specific benchmark.
        
        Args:
            name: Benchmark name
            limit: Maximum number of results to return
            
        Returns:
            List of benchmark results
        """
        history = self._benchmarks.get(name, [])
        return history[-limit:]
    
    def compare_benchmarks(self, name: str, baseline: Optional[str] = None) -> Dict[str, Any]:
        """
        Compare current benchmark performance with baseline.
        
        Args:
            name: Benchmark name
            baseline: Baseline benchmark name (uses name if None)
            
        Returns:
            Comparison statistics
        """
        if baseline is None:
            baseline = name
        
        current_results = self.get_benchmark_history(name, 10)
        baseline_results = self.get_benchmark_history(baseline, 10)
        
        if not current_results or not baseline_results:
            return {"error": "Insufficient data for comparison"}
        
        current_mean = statistics.mean([r.duration_ms for r in current_results])
        baseline_mean = statistics.mean([r.duration_ms for r in baseline_results])
        
        change_percent = ((current_mean - baseline_mean) / baseline_mean) * 100
        
        return {
            "current_mean_ms": current_mean,
            "baseline_mean_ms": baseline_mean,
            "change_percent": change_percent,
            "improvement": change_percent < 0,
        }
    
    def check_thresholds(self, metric_name: str, value: float) -> Optional[PerformanceAlert]:
        """
        Check if a metric value exceeds thresholds.
        
        Args:
            metric_name: Name of the metric
            value: Current metric value
            
        Returns:
            PerformanceAlert if threshold exceeded, None otherwise
        """
        if metric_name not in self._thresholds:
            return None
        
        thresholds = self._thresholds[metric_name]
        
        if value >= thresholds["critical"]:
            return PerformanceAlert(
                metric_name=metric_name,
                current_value=value,
                threshold_value=thresholds["critical"],
                severity="critical",
                message=f"Critical: {metric_name} = {value:.2f} exceeds threshold {thresholds['critical']:.2f}",
            )
        elif value >= thresholds["warning"]:
            return PerformanceAlert(
                metric_name=metric_name,
                current_value=value,
                threshold_value=thresholds["warning"],
                severity="warning",
                message=f"Warning: {metric_name} = {value:.2f} exceeds threshold {thresholds['warning']:.2f}",
            )
        
        return None


class PerformanceDashboard:
    """
    Performance monitoring dashboard.
    
    This class provides aerospace-level performance monitoring with
    real-time metrics, visualization, and alerting.
    """
    
    def __init__(self):
        """Initialize the performance dashboard."""
        self.benchmark = PerformanceBenchmark()
        self._metrics: Dict[str, List[tuple]] = defaultdict(list)
        self._alerts: List[PerformanceAlert] = []
        self._alerts_lock: Any = None
    
    def record_metric(self, name: str, value: float, timestamp: Optional[datetime] = None) -> None:
        """
        Record a performance metric.
        
        Args:
            name: Metric name
            value: Metric value
            timestamp: Optional timestamp (uses current time if None)
        """
        if timestamp is None:
            timestamp = datetime.utcnow()
        
        self._metrics[name].append((timestamp, value))
        
        # Check thresholds
        alert = self.benchmark.check_thresholds(name, value)
        if alert:
            self._alerts.append(alert)
    
    def get_metrics(self, name: str, duration_minutes: int = 60) -> List[tuple]:
        """
        Get metrics for a specific time window.
        
        Args:
            name: Metric name
            duration_minutes: Time window in minutes
            
        Returns:
            List of (timestamp, value) tuples
        """
        cutoff = datetime.utcnow() - timedelta(minutes=duration_minutes)
        return [(t, v) for t, v in self._metrics.get(name, []) if t >= cutoff]
    
    def get_metric_stats(self, name: str, duration_minutes: int = 60) -> Dict[str, float]:
        """
        Get statistical summary for a metric.
        
        Args:
            name: Metric name
            duration_minutes: Time window in minutes
            
        Returns:
            Dictionary with statistics
        """
        metrics = self.get_metrics(name, duration_minutes)
        values = [v for _, v in metrics]
        
        if not values:
            return {}
        
        return {
            "count": len(values),
            "mean": statistics.mean(values),
            "median": statistics.median(values),
            "min": min(values),
            "max": max(values),
            "std": statistics.stdev(values) if len(values) > 1 else 0,
        }
    
    def get_alerts(self, severity: Optional[str] = None, limit: int = 100) -> List[PerformanceAlert]:
        """
        Get performance alerts.
        
        Args:
            severity: Filter by severity (optional)
            limit: Maximum number of alerts to return
            
        Returns:
            List of performance alerts
        """
        alerts = self._alerts
        
        if severity:
            alerts = [a for a in alerts if a.severity == severity]
        
        return alerts[-limit:]
    
    def clear_alerts(self) -> None:
        """Clear all alerts."""
        self._alerts.clear()
    
    def generate_report(self) -> Dict[str, Any]:
        """
        Generate a comprehensive performance report.
        
        Returns:
            Dictionary containing performance report data
        """
        report = {
            "timestamp": datetime.utcnow().isoformat(),
            "metrics": {},
            "benchmarks": {},
            "alerts": [],
        }
        
        # Add metric statistics
        for metric_name in self._metrics:
            stats = self.get_metric_stats(metric_name)
            if stats:
                report["metrics"][metric_name] = stats
        
        # Add benchmark summaries
        for benchmark_name in self.benchmark._benchmarks:
            history = self.benchmark.get_benchmark_history(benchmark_name, 10)
            if history:
                durations = [r.duration_ms for r in history]
                report["benchmarks"][benchmark_name] = {
                    "count": len(history),
                    "mean_ms": statistics.mean(durations),
                    "median_ms": statistics.median(durations),
                }
        
        # Add recent alerts
        report["alerts"] = [
            {
                "metric": a.metric_name,
                "value": a.current_value,
                "threshold": a.threshold_value,
                "severity": a.severity,
                "message": a.message,
                "timestamp": a.timestamp.isoformat(),
            }
            for a in self.get_alerts(limit=20)
        ]
        
        return report
    
    def export_report(self, output_path: Path) -> None:
        """
        Export performance report to file.
        
        Args:
            output_path: Path to output file
        """
        report = self.generate_report()
        output_path = Path(output_path)
        
        if output_path.suffix == ".json":
            with open(output_path, "w") as f:
                json.dump(report, f, indent=2)
        else:
            # Export as text
            with open(output_path, "w") as f:
                f.write("Performance Report\n")
                f.write("=" * 50 + "\n\n")
                f.write(f"Generated: {report['timestamp']}\n\n")
                
                f.write("Metrics:\n")
                for name, stats in report["metrics"].items():
                    f.write(f"  {name}:\n")
                    for key, value in stats.items():
                        f.write(f"    {key}: {value:.2f}\n")
                
                f.write("\nBenchmarks:\n")
                for name, stats in report["benchmarks"].items():
                    f.write(f"  {name}:\n")
                    for key, value in stats.items():
                        f.write(f"    {key}: {value:.2f}\n")
                
                f.write("\nAlerts:\n")
                for alert in report["alerts"]:
                    f.write(f"  [{alert['severity']}] {alert['metric']}: {alert['message']}\n")


# Global performance dashboard instance
_global_performance_dashboard: Optional[PerformanceDashboard] = None


def get_performance_dashboard() -> PerformanceDashboard:
    """
    Get the global performance dashboard instance.
    
    Returns:
        Global PerformanceDashboard instance
    """
    global _global_performance_dashboard
    if _global_performance_dashboard is None:
        _global_performance_dashboard = PerformanceDashboard()
    return _global_performance_dashboard
