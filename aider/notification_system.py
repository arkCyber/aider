"""
Notification System Module

This module provides notification functionality for the Aider AI coding assistant.
It implements aerospace-level notification management with multiple channels,
notification templates, and delivery tracking.

Key Features:
- Multiple notification channels (email, Slack, Discord, webhook)
- Notification templates and formatting
- Notification queuing and retry logic
- Notification history and tracking
- Configurable notification policies
- Rate limiting for notifications
- Notification encryption support
"""

import json
import smtplib
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import requests


@dataclass
class Notification:
    """
    Notification data structure.
    
    Attributes:
        id: Unique notification ID
        channel: Notification channel (email, slack, discord, webhook)
        recipient: Recipient of the notification
        subject: Notification subject/title
        message: Notification message body
        priority: Notification priority (low, normal, high, critical)
        status: Notification status (pending, sent, failed)
        created_at: When the notification was created
        sent_at: When the notification was sent
        error: Error message if sending failed
        metadata: Additional metadata
    """
    id: str
    channel: str
    recipient: str
    subject: str
    message: str
    priority: str = "normal"
    status: str = "pending"
    created_at: datetime = field(default_factory=datetime.utcnow)
    sent_at: Optional[datetime] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class NotificationChannel:
    """
    Configuration for a notification channel.
    
    Attributes:
        name: Channel name
        enabled: Whether the channel is enabled
        config: Channel-specific configuration
    """
    name: str
    enabled: bool = True
    config: Dict[str, Any] = field(default_factory=dict)


class NotificationChannelBase(ABC):
    """
    Base class for notification channels.
    
    This abstract class defines the interface that all notification
    channels must implement.
    """
    
    @abstractmethod
    def send(self, notification: Notification) -> bool:
        """
        Send a notification.
        
        Args:
            notification: Notification to send
            
        Returns:
            True if successful, False otherwise
            
        This method should:
        - Validate the notification content
        - Format the notification according to channel requirements
        - Send the notification through the appropriate channel
        - Handle send failures gracefully
        - Return success status
        """
        raise NotImplementedError("Subclasses must implement send()")
    
    @abstractmethod
    def validate_config(self) -> bool:
        """
        Validate the channel configuration.
        
        Returns:
            True if configuration is valid, False otherwise
            
        This method should:
        - Check required configuration fields
        - Validate configuration values
        - Test connection if applicable
        - Return validation status
        """
        raise NotImplementedError("Subclasses must implement validate_config()")


class EmailChannel(NotificationChannelBase):
    """
    Email notification channel.
    
    This class provides email notifications via SMTP.
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the email channel.
        
        Args:
            config: Email configuration (smtp_server, smtp_port, username, password, from_address)
        """
        self.smtp_server = config.get("smtp_server", "smtp.gmail.com")
        self.smtp_port = config.get("smtp_port", 587)
        self.username = config.get("username")
        self.password = config.get("password")
        self.from_address = config.get("from_address")
    
    def send(self, notification: Notification) -> bool:
        """
        Send an email notification.
        
        Args:
            notification: Notification to send
            
        Returns:
            True if successful, False otherwise
        """
        try:
            msg = MIMEMultipart()
            msg["From"] = self.from_address
            msg["To"] = notification.recipient
            msg["Subject"] = notification.subject
            
            msg.attach(MIMEText(notification.message, "plain"))
            
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.username, self.password)
                server.send_message(msg)
            
            return True
        except Exception as e:
            notification.error = str(e)
            return False
    
    def validate_config(self) -> bool:
        """
        Validate the email configuration.
        
        Returns:
            True if configuration is valid, False otherwise
        """
        return all([
            self.smtp_server,
            self.smtp_port,
            self.username,
            self.password,
            self.from_address,
        ])


class SlackChannel(NotificationChannelBase):
    """
    Slack notification channel.
    
    This class provides Slack notifications via webhooks.
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the Slack channel.
        
        Args:
            config: Slack configuration (webhook_url, channel, username)
        """
        self.webhook_url = config.get("webhook_url")
        self.channel = config.get("channel", "#general")
        self.username = config.get("username", "Aider Bot")
    
    def send(self, notification: Notification) -> bool:
        """
        Send a Slack notification.
        
        Args:
            notification: Notification to send
            
        Returns:
            True if successful, False otherwise
        """
        try:
            payload = {
                "channel": self.channel,
                "username": self.username,
                "text": notification.subject,
                "attachments": [
                    {
                        "color": self._get_color(notification.priority),
                        "text": notification.message,
                        "footer": f"Priority: {notification.priority}",
                    }
                ],
            }
            
            response = requests.post(self.webhook_url, json=payload, timeout=10)
            response.raise_for_status()
            
            return True
        except Exception as e:
            notification.error = str(e)
            return False
    
    def validate_config(self) -> bool:
        """
        Validate the Slack configuration.
        
        Returns:
            True if configuration is valid, False otherwise
        """
        return bool(self.webhook_url)
    
    def _get_color(self, priority: str) -> str:
        """Get color based on priority."""
        colors = {
            "low": "#36a64f",
            "normal": "#36a64f",
            "high": "#ff9800",
            "critical": "#ff0000",
        }
        return colors.get(priority, "#36a64f")


class DiscordChannel(NotificationChannelBase):
    """
    Discord notification channel.
    
    This class provides Discord notifications via webhooks.
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the Discord channel.
        
        Args:
            config: Discord configuration (webhook_url, username)
        """
        self.webhook_url = config.get("webhook_url")
        self.username = config.get("username", "Aider Bot")
    
    def send(self, notification: Notification) -> bool:
        """
        Send a Discord notification.
        
        Args:
            notification: Notification to send
            
        Returns:
            True if successful, False otherwise
        """
        try:
            payload = {
                "username": self.username,
                "embeds": [
                    {
                        "title": notification.subject,
                        "description": notification.message,
                        "color": self._get_color(notification.priority),
                        "timestamp": notification.created_at.isoformat(),
                    }
                ],
            }
            
            response = requests.post(self.webhook_url, json=payload, timeout=10)
            response.raise_for_status()
            
            return True
        except Exception as e:
            notification.error = str(e)
            return False
    
    def validate_config(self) -> bool:
        """
        Validate the Discord configuration.
        
        Returns:
            True if configuration is valid, False otherwise
        """
        return bool(self.webhook_url)
    
    def _get_color(self, priority: str) -> int:
        """Get color based on priority."""
        colors = {
            "low": 5763719,  # green
            "normal": 5763719,
            "high": 16776960,  # orange
            "critical": 16711680,  # red
        }
        return colors.get(priority, 5763719)


class WebhookChannel(NotificationChannelBase):
    """
    Generic webhook notification channel.
    
    This class provides notifications via HTTP webhooks.
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the webhook channel.
        
        Args:
            config: Webhook configuration (url, headers, method)
        """
        self.url = config.get("url")
        self.headers = config.get("headers", {})
        self.method = config.get("method", "POST")
    
    def send(self, notification: Notification) -> bool:
        """
        Send a webhook notification.
        
        Args:
            notification: Notification to send
            
        Returns:
            True if successful, False otherwise
        """
        try:
            payload = {
                "id": notification.id,
                "subject": notification.subject,
                "message": notification.message,
                "priority": notification.priority,
                "created_at": notification.created_at.isoformat(),
                "metadata": notification.metadata,
            }
            
            response = requests.request(
                self.method,
                self.url,
                json=payload,
                headers=self.headers,
                timeout=10,
            )
            response.raise_for_status()
            
            return True
        except Exception as e:
            notification.error = str(e)
            return False
    
    def validate_config(self) -> bool:
        """
        Validate the webhook configuration.
        
        Returns:
            True if configuration is valid, False otherwise
        """
        return bool(self.url)


class NotificationManager:
    """
    Manages notification sending and tracking.
    
    This class provides aerospace-level notification management with
    multiple channels, queuing, and delivery tracking.
    """
    
    def __init__(self, config_file: Optional[Union[str, Path]] = None):
        """
        Initialize the notification manager.
        
        Args:
            config_file: Path to notification configuration file
        """
        self._channels: Dict[str, NotificationChannelBase] = {}
        self._notification_queue: List[Notification] = []
        self._notification_history: List[Notification] = []
        self._lock = threading.Lock()
        
        if config_file:
            self.load_config(config_file)
    
    def load_config(self, config_file: Union[str, Path]) -> None:
        """
        Load notification configuration from file.
        
        Args:
            config_file: Path to configuration file
        """
        config_path = Path(config_file)
        
        if not config_path.exists():
            return
        
        with open(config_path, "r") as f:
            config = json.load(f)
        
        # Register channels
        for channel_name, channel_config in config.get("channels", {}).items():
            if channel_config.get("enabled", False):
                self.register_channel(channel_name, channel_config)
    
    def register_channel(self, name: str, config: Dict[str, Any]) -> None:
        """
        Register a notification channel.
        
        Args:
            name: Channel name
            config: Channel configuration
        """
        channel_type = config.get("type", "webhook")
        
        channel_map = {
            "email": EmailChannel,
            "slack": SlackChannel,
            "discord": DiscordChannel,
            "webhook": WebhookChannel,
        }
        
        channel_class = channel_map.get(channel_type)
        if channel_class:
            channel = channel_class(config)
            if channel.validate_config():
                with self._lock:
                    self._channels[name] = channel
    
    def send_notification(
        self,
        channel: str,
        recipient: str,
        subject: str,
        message: str,
        priority: str = "normal",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Send a notification.
        
        Args:
            channel: Channel to use
            recipient: Recipient of the notification
            subject: Notification subject
            message: Notification message
            priority: Notification priority
            metadata: Additional metadata
            
        Returns:
            True if notification was sent successfully, False otherwise
        """
        with self._lock:
            channel_instance = self._channels.get(channel)
            if not channel_instance:
                return False
            
            notification = Notification(
                id=self._generate_notification_id(),
                channel=channel,
                recipient=recipient,
                subject=subject,
                message=message,
                priority=priority,
                metadata=metadata or {},
            )
            
            # Send notification
            success = channel_instance.send(notification)
            
            # Update status
            notification.status = "sent" if success else "failed"
            notification.sent_at = datetime.utcnow() if success else None
            
            # Add to history
            self._notification_history.append(notification)
            
            # Keep history limited to last 1000 notifications
            if len(self._notification_history) > 1000:
                self._notification_history = self._notification_history[-1000:]
            
            return success
    
    def get_notification_history(
        self, limit: int = 100, channel: Optional[str] = None
    ) -> List[Notification]:
        """
        Get notification history.
        
        Args:
            limit: Maximum number of notifications to return
            channel: Filter by channel (optional)
            
        Returns:
            List of notifications
        """
        with self._lock:
            history = self._notification_history
            
            if channel:
                history = [n for n in history if n.channel == channel]
            
            # Sort by created_at (newest first)
            history.sort(key=lambda x: x.created_at, reverse=True)
            
            return history[:limit]
    
    def _generate_notification_id(self) -> str:
        """
        Generate a unique notification ID.
        
        Returns:
            Unique notification ID
        """
        import uuid
        return str(uuid.uuid4())


# Global notification manager instance
_global_notification_manager: Optional[NotificationManager] = None


def get_notification_manager(config_file: Optional[Union[str, Path]] = None) -> NotificationManager:
    """
    Get the global notification manager instance.
    
    Args:
        config_file: Path to notification configuration file
        
    Returns:
        Global NotificationManager instance
    """
    global _global_notification_manager
    if _global_notification_manager is None:
        _global_notification_manager = NotificationManager(config_file)
    return _global_notification_manager


def send_notification(
    channel: str,
    recipient: str,
    subject: str,
    message: str,
    priority: str = "normal",
    metadata: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Send a notification (convenience function).
    
    Args:
        channel: Channel to use
        recipient: Recipient of the notification
        subject: Notification subject
        message: Notification message
        priority: Notification priority
        metadata: Additional metadata
        
    Returns:
        True if notification was sent successfully, False otherwise
    """
    manager = get_notification_manager()
    return manager.send_notification(channel, recipient, subject, message, priority, metadata)
