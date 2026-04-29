"""
Unit tests for notification system module.
"""

import unittest
from datetime import datetime

from aider.notification_system import (
    BackupManager,
    Notification,
    NotificationChannel,
    NotificationManager,
    WebhookChannel,
    get_notification_manager,
    send_notification,
)


class TestNotification(unittest.TestCase):
    """Test notification dataclass."""

    def test_notification_creation(self):
        """Test creating a notification."""
        notification = Notification(
            id="test_id",
            channel="email",
            recipient="test@example.com",
            subject="Test Subject",
            message="Test message",
            priority="normal",
        )
        
        self.assertEqual(notification.channel, "email")
        self.assertEqual(notification.recipient, "test@example.com")
        self.assertEqual(notification.status, "pending")


class TestNotificationChannel(unittest.TestCase):
    """Test notification channel dataclass."""

    def test_notification_channel_creation(self):
        """Test creating a notification channel."""
        channel = NotificationChannel(
            name="test_channel",
            enabled=True,
            config={"key": "value"},
        )
        
        self.assertEqual(channel.name, "test_channel")
        self.assertTrue(channel.enabled)


class TestWebhookChannel(unittest.TestCase):
    """Test webhook notification channel."""

    def test_webhook_channel_initialization(self):
        """Test webhook channel initialization."""
        config = {"url": "https://example.com/webhook"}
        channel = WebhookChannel(config)
        
        self.assertEqual(channel.url, "https://example.com/webhook")
        self.assertEqual(channel.method, "POST")
    
    def test_validate_config(self):
        """Test webhook configuration validation."""
        config = {"url": "https://example.com/webhook"}
        channel = WebhookChannel(config)
        
        self.assertTrue(channel.validate_config())
    
    def test_validate_config_invalid(self):
        """Test webhook configuration validation with invalid config."""
        config = {}  # Missing URL
        channel = WebhookChannel(config)
        
        self.assertFalse(channel.validate_config())


class TestNotificationManager(unittest.TestCase):
    """Test notification manager functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.manager = NotificationManager()
    
    def test_register_channel(self):
        """Test registering a notification channel."""
        config = {"url": "https://example.com/webhook", "type": "webhook"}
        self.manager.register_channel("webhook", config)
        
        # Channel should be registered (though send may fail without actual webhook)
        self.assertIn("webhook", self.manager._channels)
    
    def test_send_notification_no_channel(self):
        """Test sending notification with no registered channel."""
        result = self.manager.send_notification(
            channel="nonexistent",
            recipient="test@example.com",
            subject="Test",
            message="Test message",
        )
        
        self.assertFalse(result)
    
    def test_get_notification_history(self):
        """Test getting notification history."""
        history = self.manager.get_notification_history()
        
        self.assertIsInstance(history, list)
    
    def test_generate_notification_id(self):
        """Test notification ID generation."""
        notification_id = self.manager._generate_notification_id()
        
        self.assertIsNotNone(notification_id)
        self.assertGreater(len(notification_id), 0)


class TestGlobalNotificationManager(unittest.TestCase):
    """Test global notification manager instance."""

    def test_get_notification_manager(self):
        """Test getting global notification manager."""
        manager = get_notification_manager()
        self.assertIsNotNone(manager)
        
        # Should return same instance
        manager2 = get_notification_manager()
        self.assertIs(manager, manager2)


class TestSendNotification(unittest.TestCase):
    """Test convenience function for sending notifications."""

    def test_send_notification(self):
        """Test sending notification via convenience function."""
        # This will fail without proper channel configuration, but should not raise
        result = send_notification(
            channel="test",
            recipient="test@example.com",
            subject="Test",
            message="Test message",
        )
        
        self.assertIsInstance(result, bool)


if __name__ == "__main__":
    unittest.main()
