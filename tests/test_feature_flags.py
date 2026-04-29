"""
Unit tests for feature flags module.
"""

import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from aider.feature_flags import (
    FeatureFlag,
    FlagEvaluation,
    FeatureFlagManager,
    RolloutStrategy,
    get_feature_flag_manager,
    is_enabled,
    register_default_flags,
)


class TestFeatureFlag(unittest.TestCase):
    """Test feature flag dataclass."""

    def test_feature_flag_creation(self):
        """Test creating a feature flag."""
        flag = FeatureFlag(
            name="test_flag",
            enabled=True,
            description="Test flag",
        )
        
        self.assertEqual(flag.name, "test_flag")
        self.assertTrue(flag.enabled)


class TestFlagEvaluation(unittest.TestCase):
    """Test flag evaluation dataclass."""

    def test_flag_evaluation_creation(self):
        """Test creating a flag evaluation."""
        evaluation = FlagEvaluation(
            flag_name="test",
            enabled=True,
            reason="Test reason",
        )
        
        self.assertEqual(evaluation.flag_name, "test")
        self.assertTrue(evaluation.enabled)


class TestFeatureFlagManager(unittest.TestCase):
    """Test feature flag manager."""

    def setUp(self):
        """Set up test fixtures."""
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "feature_flags.json"
            self.manager = FeatureFlagManager(config_path)
    
    def test_register_flag(self):
        """Test registering a feature flag."""
        flag = FeatureFlag(
            name="test_flag",
            enabled=True,
        )
        self.manager.register_flag(flag)
        
        retrieved = self.manager.get_flag("test_flag")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.name, "test_flag")
    
    def test_is_enabled_all_users(self):
        """Test flag enabled for all users."""
        flag = FeatureFlag(
            name="test_flag",
            enabled=True,
            rollout_strategy=RolloutStrategy.ALL_USERS,
        )
        self.manager.register_flag(flag)
        
        result = self.manager.is_enabled("test_flag")
        self.assertTrue(result)
    
    def test_is_enabled_percentage(self):
        """Test percentage-based rollout."""
        flag = FeatureFlag(
            name="test_flag",
            enabled=True,
            rollout_strategy=RolloutStrategy.PERCENTAGE,
            rollout_percentage=100.0,
        )
        self.manager.register_flag(flag)
        
        result = self.manager.is_enabled("test_flag", user_id="user123")
        self.assertTrue(result)
    
    def test_is_enabled_user_list(self):
        """Test user list-based rollout."""
        flag = FeatureFlag(
            name="test_flag",
            enabled=True,
            rollout_strategy=RolloutStrategy.USER_LIST,
            allowed_users=["user123"],
        )
        self.manager.register_flag(flag)
        
        result = self.manager.is_enabled("test_flag", user_id="user123")
        self.assertTrue(result)
        
        result = self.manager.is_enabled("test_flag", user_id="user456")
        self.assertFalse(result)
    
    def test_update_flag(self):
        """Test updating a feature flag."""
        flag = FeatureFlag(
            name="test_flag",
            enabled=False,
        )
        self.manager.register_flag(flag)
        
        self.manager.update_flag("test_flag", enabled=True)
        
        updated = self.manager.get_flag("test_flag")
        self.assertTrue(updated.enabled)
    
    def test_delete_flag(self):
        """Test deleting a feature flag."""
        flag = FeatureFlag(
            name="test_flag",
            enabled=True,
        )
        self.manager.register_flag(flag)
        
        result = self.manager.delete_flag("test_flag")
        self.assertTrue(result)
        
        retrieved = self.manager.get_flag("test_flag")
        self.assertIsNone(retrieved)


class TestGlobalFeatureFlagManager(unittest.TestCase):
    """Test global feature flag manager instance."""

    def test_get_feature_flag_manager(self):
        """Test getting global feature flag manager."""
        manager = get_feature_flag_manager()
        self.assertIsNotNone(manager)
        
        # Should return same instance
        manager2 = get_feature_flag_manager()
        self.assertIs(manager, manager2)


class TestConvenienceFunctions(unittest.TestCase):
    """Test convenience functions."""

    def test_is_enabled(self):
        """Test is_enabled convenience function."""
        manager = get_feature_flag_manager()
        manager.register_flag(FeatureFlag(
            name="test_flag",
            enabled=True,
            rollout_strategy=RolloutStrategy.ALL_USERS,
        ))
        
        result = is_enabled("test_flag")
        self.assertTrue(result)


if __name__ == "__main__":
    unittest.main()
