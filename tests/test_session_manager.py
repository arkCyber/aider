"""
Unit tests for session manager module.
"""

import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from aider.session_manager import (
    Session,
    SessionConfig,
    SessionManager,
    get_session_manager,
)


class TestSession(unittest.TestCase):
    """Test session dataclass."""

    def test_session_creation(self):
        """Test creating a session."""
        session = Session(
            session_id="test_id",
            user_id="user123",
        )
        
        self.assertEqual(session.session_id, "test_id")
        self.assertEqual(session.user_id, "user123")
        self.assertTrue(session.is_active)


class TestSessionConfig(unittest.TestCase):
    """Test session configuration dataclass."""

    def test_session_config_creation(self):
        """Test creating session configuration."""
        config = SessionConfig(
            session_timeout_seconds=3600,
            max_sessions_per_user=5,
        )
        
        self.assertEqual(config.session_timeout_seconds, 3600)
        self.assertEqual(config.max_sessions_per_user, 5)


class TestSessionManager(unittest.TestCase):
    """Test session manager functionality."""

    def setUp(self):
        """Set up test fixtures."""
        with TemporaryDirectory() as temp_dir:
            config = SessionConfig(
                session_storage_path=Path(temp_dir),
                cleanup_interval_seconds=1,
            )
            self.manager = SessionManager(config)
    
    def test_create_session(self):
        """Test creating a session."""
        session = self.manager.create_session("user123")
        
        self.assertIsNotNone(session)
        self.assertEqual(session.user_id, "user123")
        self.assertTrue(session.is_active)
    
    def test_get_session(self):
        """Test getting a session."""
        session = self.manager.create_session("user123")
        
        retrieved = self.manager.get_session(session.session_id)
        
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.session_id, session.session_id)
    
    def test_update_session(self):
        """Test updating a session."""
        session = self.manager.create_session("user123")
        
        result = self.manager.update_session(
            session.session_id,
            context={"key": "value"},
        )
        
        self.assertTrue(result)
        
        updated = self.manager.get_session(session.session_id)
        self.assertEqual(updated.context["key"], "value")
    
    def test_delete_session(self):
        """Test deleting a session."""
        session = self.manager.create_session("user123")
        
        result = self.manager.delete_session(session.session_id)
        
        self.assertTrue(result)
        
        retrieved = self.manager.get_session(session.session_id)
        self.assertIsNone(retrieved)
    
    def test_get_user_sessions(self):
        """Test getting user sessions."""
        session1 = self.manager.create_session("user123")
        session2 = self.manager.create_session("user123")
        
        sessions = self.manager.get_user_sessions("user123")
        
        self.assertEqual(len(sessions), 2)
    
    def test_session_expiration(self):
        """Test session expiration."""
        config = SessionConfig(
            session_timeout_seconds=1,
            session_storage_path=self.manager.config.session_storage_path,
        )
        manager = SessionManager(config)
        
        session = manager.create_session("user123")
        
        # Wait for expiration
        time.sleep(2)
        
        retrieved = manager.get_session(session.session_id)
        self.assertIsNone(retrieved)
    
    def test_cleanup_expired_sessions(self):
        """Test cleaning up expired sessions."""
        config = SessionConfig(
            session_timeout_seconds=1,
            session_storage_path=self.manager.config.session_storage_path,
        )
        manager = SessionManager(config)
        
        manager.create_session("user123")
        
        # Wait for expiration
        time.sleep(2)
        
        cleaned = manager.cleanup_expired_sessions()
        
        self.assertGreater(cleaned, 0)
    
    def test_get_session_stats(self):
        """Test getting session statistics."""
        self.manager.create_session("user123")
        self.manager.create_session("user456")
        
        stats = self.manager.get_session_stats()
        
        self.assertGreater(stats["total_sessions"], 0)
        self.assertGreater(stats["unique_users"], 0)


class TestGlobalSessionManager(unittest.TestCase):
    """Test global session manager instance."""

    def test_get_session_manager(self):
        """Test getting global session manager."""
        manager = get_session_manager()
        self.assertIsNotNone(manager)
        
        # Should return same instance
        manager2 = get_session_manager()
        self.assertIs(manager, manager2)


if __name__ == "__main__":
    unittest.main()
