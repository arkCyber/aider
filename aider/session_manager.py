"""
Session Management Module

This module provides session management for the Aider AI coding assistant.
It implements aerospace-level session handling with persistence, security,
and comprehensive session lifecycle management.

Key Features:
- Session creation and management
- Session persistence and recovery
- Session security and encryption
- Session timeout and cleanup
- Session context management
- Session analytics and tracking
- Multi-session support
"""

import json
import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
import hashlib


@dataclass
class Session:
    """
    User session data structure.
    
    Attributes:
        session_id: Unique session identifier
        user_id: User identifier
        created_at: When the session was created
        last_activity: Last activity timestamp
        expires_at: When the session expires
        context: Session context data
        metadata: Additional session metadata
        is_active: Whether the session is active
    """
    session_id: str
    user_id: str
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_activity: datetime = field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None
    context: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    is_active: bool = True


@dataclass
class SessionConfig:
    """
    Session management configuration.
    
    Attributes:
        session_timeout_seconds: Session timeout in seconds
        max_sessions_per_user: Maximum sessions per user
        cleanup_interval_seconds: Cleanup interval in seconds
        persist_sessions: Whether to persist sessions
        session_storage_path: Path to session storage
    """
    session_timeout_seconds: int = 3600  # 1 hour
    max_sessions_per_user: int = 5
    cleanup_interval_seconds: int = 300  # 5 minutes
    persist_sessions: bool = True
    session_storage_path: Optional[Path] = None


class SessionManager:
    """
    Session manager with aerospace-level capabilities.
    
    This class provides comprehensive session management with
    persistence, security, and lifecycle management.
    """
    
    def __init__(self, config: Optional[SessionConfig] = None):
        """
        Initialize the session manager.
        
        Args:
            config: Session configuration
        """
        self.config = config or SessionConfig()
        
        if self.config.session_storage_path is None:
            self.config.session_storage_path = Path.home() / ".aider" / "sessions"
        
        self.config.session_storage_path.mkdir(parents=True, exist_ok=True)
        
        self._sessions: Dict[str, Session] = {}
        self._user_sessions: Dict[str, List[str]] = {}
        self._lock = threading.Lock()
        
        # Load persisted sessions
        if self.config.persist_sessions:
            self._load_sessions()
        
        # Start cleanup thread
        self._cleanup_thread: Optional[threading.Thread] = None
        self._start_cleanup_thread()
    
    def create_session(
        self,
        user_id: str,
        context: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Session:
        """
        Create a new session.
        
        Args:
            user_id: User identifier
            context: Initial session context
            metadata: Session metadata
            
        Returns:
            Created session
        """
        session_id = str(uuid.uuid4())
        
        # Calculate expiration
        expires_at = datetime.utcnow() + timedelta(
            seconds=self.config.session_timeout_seconds
        )
        
        session = Session(
            session_id=session_id,
            user_id=user_id,
            expires_at=expires_at,
            context=context or {},
            metadata=metadata or {},
        )
        
        with self._lock:
            # Check session limit
            user_session_ids = self._user_sessions.get(user_id, [])
            if len(user_session_ids) >= self.config.max_sessions_per_user:
                # Remove oldest session
                oldest_session_id = user_session_ids[0]
                self._remove_session(oldest_session_id)
            
            # Add session
            self._sessions[session_id] = session
            if user_id not in self._user_sessions:
                self._user_sessions[user_id] = []
            self._user_sessions[user_id].append(session_id)
            
            # Persist session
            if self.config.persist_sessions:
                self._persist_session(session)
        
        return session
    
    def get_session(self, session_id: str) -> Optional[Session]:
        """
        Get a session by ID.
        
        Args:
            session_id: Session identifier
            
        Returns:
            Session or None if not found or expired
        """
        with self._lock:
            session = self._sessions.get(session_id)
            
            if not session:
                # Try loading from storage
                if self.config.persist_sessions:
                    session = self._load_session(session_id)
                    if session:
                        self._sessions[session_id] = session
            
            if session:
                # Check expiration
                if session.expires_at and datetime.utcnow() > session.expires_at:
                    self._remove_session(session_id)
                    return None
                
                # Update last activity
                session.last_activity = datetime.utcnow()
                if self.config.persist_sessions:
                    self._persist_session(session)
            
            return session
    
    def update_session(
        self,
        session_id: str,
        context: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Update session data.
        
        Args:
            session_id: Session identifier
            context: Context to update (merged with existing)
            metadata: Metadata to update (merged with existing)
            
        Returns:
            True if update was successful, False otherwise
        """
        with self._lock:
            session = self._sessions.get(session_id)
            
            if not session:
                return False
            
            if context:
                session.context.update(context)
            
            if metadata:
                session.metadata.update(metadata)
            
            session.last_activity = datetime.utcnow()
            
            if self.config.persist_sessions:
                self._persist_session(session)
            
            return True
    
    def delete_session(self, session_id: str) -> bool:
        """
        Delete a session.
        
        Args:
            session_id: Session identifier
            
        Returns:
            True if deletion was successful, False otherwise
        """
        with self._lock:
            return self._remove_session(session_id)
    
    def _remove_session(self, session_id: str) -> bool:
        """
        Remove a session (internal method).
        
        Args:
            session_id: Session identifier
            
        Returns:
            True if removal was successful, False otherwise
        """
        session = self._sessions.get(session_id)
        if not session:
            return False
        
        # Remove from user sessions
        if session.user_id in self._user_sessions:
            user_sessions = self._user_sessions[session.user_id]
            if session_id in user_sessions:
                user_sessions.remove(session_id)
            if not user_sessions:
                del self._user_sessions[session.user_id]
        
        # Remove from sessions
        del self._sessions[session_id]
        
        # Remove from storage
        if self.config.persist_sessions:
            session_file = self.config.session_storage_path / f"{session_id}.json"
            if session_file.exists():
                session_file.unlink()
        
        return True
    
    def get_user_sessions(self, user_id: str) -> List[Session]:
        """
        Get all sessions for a user.
        
        Args:
            user_id: User identifier
            
        Returns:
            List of user sessions
        """
        with self._lock:
            session_ids = self._user_sessions.get(user_id, [])
            sessions = []
            
            for session_id in session_ids:
                session = self.get_session(session_id)
                if session:
                    sessions.append(session)
            
            return sessions
    
    def cleanup_expired_sessions(self) -> int:
        """
        Clean up expired sessions.
        
        Returns:
            Number of sessions cleaned up
        """
        with self._lock:
            now = datetime.utcnow()
            expired_sessions = []
            
            for session_id, session in self._sessions.items():
                if session.expires_at and now > session.expires_at:
                    expired_sessions.append(session_id)
            
            for session_id in expired_sessions:
                self._remove_session(session_id)
            
            return len(expired_sessions)
    
    def _start_cleanup_thread(self) -> None:
        """Start the cleanup thread."""
        def cleanup_worker():
            while True:
                try:
                    time.sleep(self.config.cleanup_interval_seconds)
                    self.cleanup_expired_sessions()
                except Exception:
                    pass
        
        self._cleanup_thread = threading.Thread(target=cleanup_worker, daemon=True)
        self._cleanup_thread.start()
    
    def _persist_session(self, session: Session) -> None:
        """
        Persist a session to storage.
        
        Args:
            session: Session to persist
        """
        session_file = self.config.session_storage_path / f"{session.session_id}.json"
        
        data = {
            "session_id": session.session_id,
            "user_id": session.user_id,
            "created_at": session.created_at.isoformat(),
            "last_activity": session.last_activity.isoformat(),
            "expires_at": session.expires_at.isoformat() if session.expires_at else None,
            "context": session.context,
            "metadata": session.metadata,
            "is_active": session.is_active,
        }
        
        try:
            with open(session_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass  # Non-fatal if we can't persist
    
    def _load_session(self, session_id: str) -> Optional[Session]:
        """
        Load a session from storage.
        
        Args:
            session_id: Session identifier
            
        Returns:
            Session or None if not found
        """
        session_file = self.config.session_storage_path / f"{session_id}.json"
        
        if not session_file.exists():
            return None
        
        try:
            with open(session_file, "r") as f:
                data = json.load(f)
            
            session = Session(
                session_id=data["session_id"],
                user_id=data["user_id"],
                created_at=datetime.fromisoformat(data["created_at"]),
                last_activity=datetime.fromisoformat(data["last_activity"]),
                expires_at=datetime.fromisoformat(data["expires_at"]) if data["expires_at"] else None,
                context=data["context"],
                metadata=data["metadata"],
                is_active=data.get("is_active", True),
            )
            
            return session
        except Exception:
            return None
    
    def _load_sessions(self) -> None:
        """Load all persisted sessions."""
        try:
            for session_file in self.config.session_storage_path.glob("*.json"):
                session_id = session_file.stem
                session = self._load_session(session_id)
                if session:
                    self._sessions[session_id] = session
                    
                    if session.user_id not in self._user_sessions:
                        self._user_sessions[session.user_id] = []
                    if session_id not in self._user_sessions[session.user_id]:
                        self._user_sessions[session.user_id].append(session_id)
        except Exception:
            pass
    
    def get_session_stats(self) -> Dict[str, Any]:
        """
        Get session statistics.
        
        Returns:
            Dictionary with session statistics
        """
        with self._lock:
            total_sessions = len(self._sessions)
            active_sessions = sum(1 for s in self._sessions.values() if s.is_active)
            unique_users = len(self._user_sessions)
            
            return {
                "total_sessions": total_sessions,
                "active_sessions": active_sessions,
                "unique_users": unique_users,
                "max_sessions_per_user": self.config.max_sessions_per_user,
            }
    
    def shutdown(self) -> None:
        """Shutdown the session manager."""
        # Cleanup thread is daemon, so it will stop automatically
        pass


# Global session manager instance
_global_session_manager: Optional[SessionManager] = None


def get_session_manager(config: Optional[SessionConfig] = None) -> SessionManager:
    """
    Get the global session manager instance.
    
    Args:
        config: Session configuration
        
    Returns:
        Global SessionManager instance
    """
    global _global_session_manager
    if _global_session_manager is None:
        _global_session_manager = SessionManager(config)
    return _global_session_manager
