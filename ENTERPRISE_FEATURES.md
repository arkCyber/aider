# Enterprise Features Documentation

This document provides usage examples and documentation for the new enterprise-level features added to Aider.

## Table of Contents

1. [Enhanced Logging](#enhanced-logging)
2. [Configuration Validation](#configuration-validation)
3. [Rate Limiting](#rate-limiting)
4. [Health Checking](#health-checking)
5. [Performance Monitoring](#performance-monitoring)
6. [Backup and Restore](#backup-and-restore)
7. [Notification System](#notification-system)
8. [Internationalization (i18n)](#internationalization)
9. [Feature Flags](#feature-flags)
10. [Session Management](#session-management)
11. [Code Quality Gates](#code-quality-gates)

---

## Enhanced Logging

### Overview

The enhanced logging system provides structured JSON logging with log rotation, performance tracking, and audit trails.

### Usage Example

```python
from aider.logging_config import setup_logging, AuditLogger, PerformanceLogger

# Setup enhanced logging
setup_logging(
    log_level="INFO",
    log_dir=".aider_logs",
    enable_console=True,
    enable_json=True,
)

# Use audit logger
audit_logger = AuditLogger()
audit_logger.log_command_start("test_command", "arg1 arg2", "user123")

# Use performance logger
perf_logger = PerformanceLogger()
perf_logger.start_timer("operation")
# ... perform operation ...
duration = perf_logger.end_timer("operation")
print(f"Operation took {duration:.2f} seconds")
```

### Log Files

- `.aider_logs/aider.log` - Human-readable text logs
- `.aider_logs/aider_structured.log` - Structured JSON logs
- `.aider_logs/aider_audit.log` - Audit trail logs
- `.aider_logs/aider_performance.log` - Performance metrics

---

## Configuration Validation

### Overview

The configuration validation system validates configuration files against a schema, with type checking, range validation, and security policy enforcement.

### Usage Example

```python
from aider.config_validator import ConfigValidator, validate_config_file

# Validate configuration file
result = validate_config_file("config.json")

if result.is_valid:
    print("Configuration is valid!")
    config = result.validated_config
else:
    print("Configuration validation failed:")
    for error in result.errors:
        print(f"  - {error.field}: {error.message}")
```

### Generate Configuration Template

```python
from aider.config_validator import generate_config_template

# Generate template
template = generate_config_template("config_template.yaml")
print(template)
```

---

## Rate Limiting

### Overview

The rate limiting system implements token bucket and sliding window algorithms for API call rate limiting.

### Usage Example

```python
from aider.rate_limiter import RateLimiter, RateLimitPolicy, check_rate_limit

# Setup rate limiter
policy = RateLimitPolicy(
    requests_per_minute=60,
    requests_per_hour=1000,
    requests_per_day=10000,
)
limiter = RateLimiter(policy)

# Check if request is allowed
info = limiter.is_allowed("user123")
if info.is_limited:
    print(f"Rate limited. Retry after {info.retry_after:.2f} seconds")
else:
    print(f"Request allowed. {info.remaining_requests} requests remaining")

# Convenience function
is_allowed, retry_after = check_rate_limit("user123")
```

---

## Health Checking

### Overview

The health checking system monitors system components (filesystem, Python environment, Git, dependencies, disk space, memory).

### Usage Example

```python
from aider.health_check import HealthChecker, check_system_health

# Check all components
health = check_system_health()

print(f"System is {health.status}")
for check in health.checks:
    print(f"  {check.component}: {check.status} - {check.message}")

# Check specific component
checker = HealthChecker()
result = checker.check_component("filesystem")
print(f"Filesystem: {result.status}")
```

---

## Performance Monitoring

### Overview

The performance monitoring system collects metrics, profiles code, and monitors system resources.

### Usage Example

```python
from aider.performance_monitor import PerformanceMonitor, get_performance_monitor

# Get performance monitor
monitor = get_performance_monitor()

# Record metrics
monitor.record_metric("api_latency", 0.5, tags={"endpoint": "/chat"})
monitor.record_metric("memory_usage", 1024.0)

# Get performance report
report = monitor.get_performance_report()
print(json.dumps(report, indent=2))
```

### Code Profiling

```python
from aider.performance_monitor import PerformanceProfiler

profiler = PerformanceProfiler()

# Profile a function
def test_function():
    time.sleep(0.1)
    return 42

result, stats = profiler.profile_function(test_function)
print(f"Result: {result}")
print(f"Stats: {stats}")
```

---

## Backup and Restore

### Overview

The backup and restore system provides configuration, history, and model configuration backup with compression and integrity checking.

### Usage Example

```python
from aider.backup_restore import BackupManager, get_backup_manager

# Get backup manager
manager = get_backup_manager()

# Backup configuration
metadata = manager.backup_config("config.json")
print(f"Backup created: {metadata.backup_id}")

# Backup history
metadata = manager.backup_history("history.json")
print(f"Backup created: {metadata.backup_id}")

# Full backup
metadata = manager.backup_full(
    "config.json",
    "history.json",
    "models.json",
)
print(f"Full backup created: {metadata.backup_id}")

# List backups
backups = manager.list_backups()
for backup in backups:
    print(f"{backup.backup_id}: {backup.backup_type} ({backup.timestamp})")

# Restore configuration
result = manager.restore_config(backup_id, "restore_path")
if result.success:
    print(f"Restored {result.files_restored} files")
```

---

## Notification System

### Overview

The notification system supports multiple channels (email, Slack, Discord, webhook) for sending notifications.

### Configuration Example

Create a notification configuration file `notifications.json`:

```json
{
  "channels": {
    "email": {
      "type": "email",
      "enabled": false,
      "smtp_server": "smtp.gmail.com",
      "smtp_port": 587,
      "username": "your-email@gmail.com",
      "password": "your-password",
      "from_address": "your-email@gmail.com"
    },
    "slack": {
      "type": "slack",
      "enabled": false,
      "webhook_url": "https://hooks.slack.com/services/...",
      "channel": "#general",
      "username": "Aider Bot"
    },
    "webhook": {
      "type": "webhook",
      "enabled": false,
      "url": "https://example.com/webhook",
      "method": "POST"
    }
  }
}
```

### Usage Example

```python
from aider.notification_system import NotificationManager, send_notification

# Load configuration
manager = NotificationManager("notifications.json")

# Send notification
success = manager.send_notification(
    channel="webhook",
    recipient="https://example.com/webhook",
    subject="Aider Alert",
    message="Code generation completed successfully",
    priority="normal",
    metadata={"project": "my-project"},
)

if success:
    print("Notification sent successfully")
```

---

## Integration with Existing Code

### Quick Start

```python
from aider.integration import initialize_enterprise_features

# Initialize all enterprise features
enterprise = initialize_enterprise_features("config.json")

# Get system health
health = enterprise.get_system_health()
print(f"System health: {health.status}")

# Get performance report
report = enterprise.get_performance_report()
print(f"Performance metrics: {len(report['metrics'])} metrics")

# Shutdown gracefully
enterprise.shutdown()
```

---

## Best Practices

1. **Logging**: Always use structured logging for production environments
2. **Configuration**: Validate configuration on startup
3. **Rate Limiting**: Set appropriate limits for your API usage
4. **Health Checks**: Run health checks regularly
5. **Performance Monitoring**: Monitor key metrics continuously
6. **Backups**: Schedule regular backups
7. **Notifications**: Configure notifications for critical events

---

## Security Considerations

- Store API keys and passwords securely (use environment variables)
- Enable audit logging for compliance
- Use encryption for sensitive backups
- Validate all configuration inputs
- Monitor for unusual activity patterns

---

## Troubleshooting

### Logging Issues

If logs are not being written:
- Check write permissions for log directory
- Verify log level settings
- Check disk space

### Rate Limiting

If rate limiting is too strict:
- Adjust rate limit policy
- Check for concurrent requests
- Monitor rate limit status

### Health Checks

If health checks fail:
- Check system resources (disk, memory)
- Verify dependencies are installed
- Check file permissions

### Backups

If backups fail:
- Check write permissions for backup directory
- Verify source files exist
- Check disk space

### Notifications

If notifications fail:
- Verify channel configuration
- Check network connectivity
- Verify API keys and credentials

---

## Internationalization (i18n)

### Overview

The internationalization system provides multi-language support with gettext integration, supporting runtime language switching between English, Chinese, and other languages.

### Usage Example

```python
from aider.i18n import set_language, get_language, translate, _

# Set language
set_language("zh")  # Switch to Chinese
set_language("en")  # Switch to English

# Get current language
current_lang = get_language()
print(f"Current language: {current_lang}")

# Translate messages
message = translate("AI Pair Programming in Your Terminal")
# Or use shorthand
message = _("Operation completed successfully")
```

### Supported Languages

- English (en)
- Chinese (zh)

### Adding New Languages

To add a new language:
1. Create a translation file in `locales/{lang}/LC_MESSAGES/aider.po`
2. Add translations for all messages
3. Compile the translation file

---

## Feature Flags

### Overview

The feature flag system provides dynamic feature configuration with multiple rollout strategies (percentage-based, user-based, time-based, environment-based), supporting A/B testing and gradual rollouts.

### Usage Example

```python
from aider.feature_flags import get_feature_flag_manager, is_enabled

# Check if a feature is enabled
if is_enabled("new_ui", user_id="user123"):
    # Use new UI
    pass
else:
    # Use old UI
    pass

# Get feature flag manager for advanced usage
manager = get_feature_flag_manager()

# Register a new flag
from aider.feature_flags import FeatureFlag, RolloutStrategy
flag = FeatureFlag(
    name="experimental_feature",
    enabled=True,
    rollout_strategy=RolloutStrategy.PERCENTAGE,
    rollout_percentage=10.0,
)
manager.register_flag(flag)

# Get flag usage statistics
stats = manager.get_flag_usage_stats("experimental_feature")
print(f"Enabled percentage: {stats['enabled_percentage']:.2f}%")
```

### Rollout Strategies

- **ALL_USERS**: Enable for all users
- **PERCENTAGE**: Enable for a percentage of users (consistent per user)
- **USER_LIST**: Enable for specific user IDs
- **USER_ATTRIBUTE**: Enable based on user attributes
- **TIME_BASED**: Enable during a specific time window
- **ENVIRONMENT**: Enable for specific environments (dev, staging, prod)

---

## Session Management

### Overview

The session management system provides comprehensive session handling with persistence, security, and lifecycle management, including session timeout, cleanup, and context management.

### Usage Example

```python
from aider.session_manager import get_session_manager, SessionConfig

# Get session manager
manager = get_session_manager()

# Create a session
session = manager.create_session(
    user_id="user123",
    context={"project": "my-project"},
    metadata={"ip": "192.168.1.1"},
)

# Get session
retrieved_session = manager.get_session(session.session_id)

# Update session context
manager.update_session(
    session.session_id,
    context={"new_key": "new_value"},
)

# Get all user sessions
user_sessions = manager.get_user_sessions("user123")

# Delete session
manager.delete_session(session.session_id)

# Get session statistics
stats = manager.get_session_stats()
print(f"Total sessions: {stats['total_sessions']}")
```

### Session Configuration

```python
from aider.session_manager import SessionConfig

config = SessionConfig(
    session_timeout_seconds=3600,  # 1 hour
    max_sessions_per_user=5,
    cleanup_interval_seconds=300,  # 5 minutes
    persist_sessions=True,
)
manager = get_session_manager(config)
```

---

## Code Quality Gates

### Overview

The code quality gates system provides automated code quality enforcement with configurable rules, including complexity analysis, duplication detection, code length checks, and custom quality rules.

### Usage Example

```python
from aider.code_quality_gates import get_code_quality_gates

# Get code quality gates manager
manager = get_code_quality_gates()

# Run all quality gates
results = manager.run_all_gates(Path("/path/to/code"))

# Generate quality report
report = manager.generate_report(results)
print(f"Overall status: {report['overall_status']}")
print(f"Total issues: {report['total_issues']}")
print(f"Critical issues: {report['critical_issues']}")

# Check specific gate
complexity_gate = manager.get_gate("complexity")
if complexity_gate:
    result = complexity_gate.check_directory(Path("/path/to/code"))
    print(f"Complexity gate status: {result.status}")
```

### Built-in Quality Rules

- **Cyclomatic Complexity**: Detect functions with high complexity
- **Code Duplication**: Detect duplicated code blocks
- **Code Length**: Detect files exceeding maximum length

### Custom Quality Rules

```python
from aider.code_quality_gates import QualityRule, QualityIssue, QualitySeverity

class CustomRule(QualityRule):
    def check(self, file_path: Path) -> List[QualityIssue]:
        # Implement custom check logic
        issues = []
        # ... check logic ...
        return issues

# Add custom rule to gate
gate = manager.get_gate("custom_gate")
gate.add_custom_rule(CustomRule("custom_rule"))
```

---

## Support

For issues or questions about enterprise features:
- Check the documentation
- Review the unit tests for usage examples
- Enable debug logging for detailed information
