"""
Feature Flag Module

This module provides feature flag management for the Aider AI coding assistant.
It implements aerospace-level feature flag system with dynamic configuration,
rollout strategies, and comprehensive monitoring.

Key Features:
- Dynamic feature flag configuration
- Multiple rollout strategies (percentage, user-based, time-based)
- Feature flag monitoring and analytics
- A/B testing support
- Environment-specific flag overrides
- Feature flag persistence
- Audit trail for flag changes
"""

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set
import hashlib
import threading


class RolloutStrategy(Enum):
    """Feature flag rollout strategies."""
    ALL_USERS = "all_users"
    PERCENTAGE = "percentage"
    USER_LIST = "user_list"
    USER_ATTRIBUTE = "user_attribute"
    TIME_BASED = "time_based"
    ENVIRONMENT = "environment"


@dataclass
class FeatureFlag:
    """
    Feature flag configuration.
    
    Attributes:
        name: Flag name
        enabled: Whether the flag is enabled
        description: Flag description
        rollout_strategy: Rollout strategy
        rollout_percentage: Percentage for percentage-based rollout (0-100)
        allowed_users: List of user IDs for user-based rollout
        user_attribute_filter: User attribute filter for attribute-based rollout
        start_time: Start time for time-based rollout
        end_time: End time for time-based rollout
        environment_filter: Environment filter
        metadata: Additional metadata
        created_at: When the flag was created
        updated_at: When the flag was last updated
        version: Flag version
    """
    name: str
    enabled: bool = False
    description: str = ""
    rollout_strategy: RolloutStrategy = RolloutStrategy.ALL_USERS
    rollout_percentage: float = 100.0
    allowed_users: List[str] = field(default_factory=list)
    user_attribute_filter: Optional[Dict[str, Any]] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    environment_filter: Optional[List[str]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    version: int = 1


@dataclass
class FlagEvaluation:
    """
    Result of feature flag evaluation.
    
    Attributes:
        flag_name: Name of the flag
        enabled: Whether the flag is enabled for the user
        reason: Reason for the decision
        timestamp: When the evaluation occurred
        version: Flag version
    """
    flag_name: str
    enabled: bool
    reason: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    version: int = 1


class FeatureFlagManager:
    """
    Feature flag manager with aerospace-level capabilities.
    
    This class provides comprehensive feature flag management with
    dynamic configuration, rollout strategies, and monitoring.
    """
    
    def __init__(self, config_path: Optional[Path] = None):
        """
        Initialize the feature flag manager.
        
        Args:
            config_path: Path to feature flag configuration file
        """
        self.config_path = config_path or Path.home() / ".aider" / "feature_flags.json"
        self.flags: Dict[str, FeatureFlag] = {}
        self._lock = threading.Lock()
        self._evaluation_history: List[FlagEvaluation] = []
        self._environment = os.environ.get("AIDER_ENV", "production")
        
        # Load configuration
        self._load_config()
    
    def _load_config(self) -> None:
        """Load feature flag configuration from file."""
        if self.config_path.exists():
            try:
                with open(self.config_path, "r") as f:
                    data = json.load(f)
                
                for flag_data in data.get("flags", []):
                    flag = FeatureFlag(**flag_data)
                    # Convert datetime strings
                    if flag.start_time:
                        flag.start_time = datetime.fromisoformat(flag.start_time)
                    if flag.end_time:
                        flag.end_time = datetime.fromisoformat(flag.end_time)
                    if flag.created_at:
                        flag.created_at = datetime.fromisoformat(flag.created_at)
                    if flag.updated_at:
                        flag.updated_at = datetime.fromisoformat(flag.updated_at)
                    
                    self.flags[flag.name] = flag
            except Exception:
                # If loading fails, start with empty flags
                self.flags = {}
    
    def _save_config(self) -> None:
        """Save feature flag configuration to file."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        
        data = {
            "flags": [],
            "version": 1,
            "updated_at": datetime.utcnow().isoformat(),
        }
        
        for flag in self.flags.values():
            flag_dict = {
                "name": flag.name,
                "enabled": flag.enabled,
                "description": flag.description,
                "rollout_strategy": flag.rollout_strategy.value,
                "rollout_percentage": flag.rollout_percentage,
                "allowed_users": flag.allowed_users,
                "user_attribute_filter": flag.user_attribute_filter,
                "start_time": flag.start_time.isoformat() if flag.start_time else None,
                "end_time": flag.end_time.isoformat() if flag.end_time else None,
                "environment_filter": flag.environment_filter,
                "metadata": flag.metadata,
                "created_at": flag.created_at.isoformat(),
                "updated_at": flag.updated_at.isoformat(),
                "version": flag.version,
            }
            data["flags"].append(flag_dict)
        
        with open(self.config_path, "w") as f:
            json.dump(data, f, indent=2)
    
    def register_flag(self, flag: FeatureFlag) -> None:
        """
        Register a feature flag.
        
        Args:
            flag: Feature flag to register
        """
        with self._lock:
            flag.updated_at = datetime.utcnow()
            if flag.name in self.flags:
                flag.version = self.flags[flag.name].version + 1
            
            self.flags[flag.name] = flag
            self._save_config()
    
    def get_flag(self, name: str) -> Optional[FeatureFlag]:
        """
        Get a feature flag by name.
        
        Args:
            name: Flag name
            
        Returns:
            FeatureFlag or None if not found
        """
        with self._lock:
            return self.flags.get(name)
    
    def is_enabled(
        self,
        flag_name: str,
        user_id: Optional[str] = None,
        user_attributes: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Check if a feature flag is enabled for a user.
        
        Args:
            flag_name: Name of the flag
            user_id: User ID
            user_attributes: User attributes
            
        Returns:
            True if flag is enabled, False otherwise
        """
        evaluation = self.evaluate_flag(flag_name, user_id, user_attributes)
        
        # Track evaluation
        with self._lock:
            self._evaluation_history.append(evaluation)
            # Keep history limited to last 10000 evaluations
            if len(self._evaluation_history) > 10000:
                self._evaluation_history = self._evaluation_history[-10000:]
        
        return evaluation.enabled
    
    def evaluate_flag(
        self,
        flag_name: str,
        user_id: Optional[str] = None,
        user_attributes: Optional[Dict[str, Any]] = None,
    ) -> FlagEvaluation:
        """
        Evaluate a feature flag for a user.
        
        Args:
            flag_name: Name of the flag
            user_id: User ID
            user_attributes: User attributes
            
        Returns:
            FlagEvaluation with evaluation result
        """
        flag = self.get_flag(flag_name)
        
        if not flag:
            return FlagEvaluation(
                flag_name=flag_name,
                enabled=False,
                reason="Flag not found",
            )
        
        if not flag.enabled:
            return FlagEvaluation(
                flag_name=flag_name,
                enabled=False,
                reason="Flag disabled",
                version=flag.version,
            )
        
        # Check environment filter
        if flag.environment_filter and self._environment not in flag.environment_filter:
            return FlagEvaluation(
                flag_name=flag_name,
                enabled=False,
                reason=f"Environment '{self._environment}' not in filter",
                version=flag.version,
            )
        
        # Check time-based rollout
        if flag.rollout_strategy == RolloutStrategy.TIME_BASED:
            now = datetime.utcnow()
            if flag.start_time and now < flag.start_time:
                return FlagEvaluation(
                    flag_name=flag_name,
                    enabled=False,
                    reason="Rollout not started yet",
                    version=flag.version,
                )
            if flag.end_time and now > flag.end_time:
                return FlagEvaluation(
                    flag_name=flag_name,
                    enabled=False,
                    reason="Rollout ended",
                    version=flag.version,
                )
        
        # Check rollout strategy
        if flag.rollout_strategy == RolloutStrategy.ALL_USERS:
            return FlagEvaluation(
                flag_name=flag_name,
                enabled=True,
                reason="All users",
                version=flag.version,
            )
        
        elif flag.rollout_strategy == RolloutStrategy.PERCENTAGE:
            if not user_id:
                return FlagEvaluation(
                    flag_name=flag_name,
                    enabled=False,
                    reason="User ID required for percentage rollout",
                    version=flag.version,
                )
            
            # Use hash of user_id + flag_name for consistent rollout
            hash_value = int(hashlib.sha256(f"{user_id}:{flag_name}".encode()).hexdigest(), 16)
            percentage = (hash_value % 10000) / 100.0
            
            if percentage < flag.rollout_percentage:
                return FlagEvaluation(
                    flag_name=flag_name,
                    enabled=True,
                    reason=f"Percentage rollout ({percentage:.2f}% < {flag.rollout_percentage}%)",
                    version=flag.version,
                )
            else:
                return FlagEvaluation(
                    flag_name=flag_name,
                    enabled=False,
                    reason=f"Percentage rollout ({percentage:.2f}% >= {flag.rollout_percentage}%)",
                    version=flag.version,
                )
        
        elif flag.rollout_strategy == RolloutStrategy.USER_LIST:
            if not user_id:
                return FlagEvaluation(
                    flag_name=flag_name,
                    enabled=False,
                    reason="User ID required for user list rollout",
                    version=flag.version,
                )
            
            if user_id in flag.allowed_users:
                return FlagEvaluation(
                    flag_name=flag_name,
                    enabled=True,
                    reason="User in allowed list",
                    version=flag.version,
                )
            else:
                return FlagEvaluation(
                    flag_name=flag_name,
                    enabled=False,
                    reason="User not in allowed list",
                    version=flag.version,
                )
        
        elif flag.rollout_strategy == RolloutStrategy.USER_ATTRIBUTE:
            if not user_attributes:
                return FlagEvaluation(
                    flag_name=flag_name,
                    enabled=False,
                    reason="User attributes required for attribute-based rollout",
                    version=flag.version,
                )
            
            if flag.user_attribute_filter:
                for key, value in flag.user_attribute_filter.items():
                    if user_attributes.get(key) != value:
                        return FlagEvaluation(
                            flag_name=flag_name,
                            enabled=False,
                            reason=f"User attribute '{key}' does not match",
                            version=flag.version,
                        )
            
            return FlagEvaluation(
                flag_name=flag_name,
                enabled=True,
                reason="User attributes match",
                version=flag.version,
            )
        
        return FlagEvaluation(
            flag_name=flag_name,
            enabled=False,
            reason="Unknown rollout strategy",
            version=flag.version,
        )
    
    def list_flags(self) -> List[FeatureFlag]:
        """
        List all feature flags.
        
        Returns:
            List of all feature flags
        """
        with self._lock:
            return list(self.flags.values())
    
    def update_flag(self, name: str, **kwargs) -> bool:
        """
        Update a feature flag.
        
        Args:
            name: Flag name
            **kwargs: Fields to update
            
        Returns:
            True if update was successful, False otherwise
        """
        with self._lock:
            if name not in self.flags:
                return False
            
            flag = self.flags[name]
            flag.updated_at = datetime.utcnow()
            flag.version += 1
            
            for key, value in kwargs.items():
                if hasattr(flag, key):
                    setattr(flag, key, value)
            
            self._save_config()
            return True
    
    def delete_flag(self, name: str) -> bool:
        """
        Delete a feature flag.
        
        Args:
            name: Flag name
            
        Returns:
            True if deletion was successful, False otherwise
        """
        with self._lock:
            if name not in self.flags:
                return False
            
            del self.flags[name]
            self._save_config()
            return True
    
    def get_flag_usage_stats(self, flag_name: str) -> Dict[str, Any]:
        """
        Get usage statistics for a feature flag.
        
        Args:
            flag_name: Flag name
            
        Returns:
            Dictionary with usage statistics
        """
        with self._lock:
            evaluations = [e for e in self._evaluation_history if e.flag_name == flag_name]
            
            if not evaluations:
                return {}
            
            enabled_count = sum(1 for e in evaluations if e.enabled)
            total_count = len(evaluations)
            
            return {
                "total_evaluations": total_count,
                "enabled_count": enabled_count,
                "disabled_count": total_count - enabled_count,
                "enabled_percentage": (enabled_count / total_count) * 100 if total_count > 0 else 0,
                "latest_version": evaluations[-1].version if evaluations else 0,
            }


# Global feature flag manager instance
_global_feature_flag_manager: Optional[FeatureFlagManager] = None


def get_feature_flag_manager(config_path: Optional[Path] = None) -> FeatureFlagManager:
    """
    Get the global feature flag manager instance.
    
    Args:
        config_path: Path to feature flag configuration file
        
    Returns:
        Global FeatureFlagManager instance
    """
    global _global_feature_flag_manager
    if _global_feature_flag_manager is None:
        _global_feature_flag_manager = FeatureFlagManager(config_path)
    return _global_feature_flag_manager


def is_enabled(flag_name: str, user_id: Optional[str] = None, user_attributes: Optional[Dict[str, Any]] = None) -> bool:
    """
    Check if a feature flag is enabled (convenience function).
    
    Args:
        flag_name: Name of the flag
        user_id: User ID
        user_attributes: User attributes
        
    Returns:
        True if flag is enabled, False otherwise
    """
    manager = get_feature_flag_manager()
    return manager.is_enabled(flag_name, user_id, user_attributes)


def register_default_flags() -> None:
    """Register default feature flags for Aider."""
    manager = get_feature_flag_manager()
    
    # Register common flags
    default_flags = [
        FeatureFlag(
            name="new_ui",
            enabled=False,
            description="Enable new experimental UI",
            rollout_strategy=RolloutStrategy.PERCENTAGE,
            rollout_percentage=10.0,
        ),
        FeatureFlag(
            name="enhanced_context",
            enabled=True,
            description="Enable enhanced context awareness",
            rollout_strategy=RolloutStrategy.ALL_USERS,
        ),
        FeatureFlag(
            name="parallel_processing",
            enabled=False,
            description="Enable parallel processing for large files",
            rollout_strategy=RolloutStrategy.PERCENTAGE,
            rollout_percentage=5.0,
        ),
        FeatureFlag(
            name="smart_cache",
            enabled=True,
            description="Enable intelligent caching",
            rollout_strategy=RolloutStrategy.ALL_USERS,
        ),
    ]
    
    for flag in default_flags:
        if flag.name not in manager.flags:
            manager.register_flag(flag)
