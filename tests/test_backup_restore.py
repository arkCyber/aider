"""
Unit tests for backup and restore module.
"""

import json
import tarfile
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from aider.backup_restore import (
    BackupManager,
    BackupMetadata,
    RestoreResult,
    get_backup_manager,
)


class TestBackupMetadata(unittest.TestCase):
    """Test backup metadata dataclass."""

    def test_backup_metadata_creation(self):
        """Test creating backup metadata."""
        metadata = BackupMetadata(
            backup_id="test_id",
            timestamp=datetime.utcnow(),
            backup_type="config",
            size_bytes=1024,
            checksum="abc123",
            encrypted=False,
            compressed=True,
        )
        
        self.assertEqual(metadata.backup_id, "test_id")
        self.assertEqual(metadata.backup_type, "config")
        self.assertFalse(metadata.encrypted)


class TestRestoreResult(unittest.TestCase):
    """Test restore result dataclass."""

    def test_restore_result_creation(self):
        """Test creating a restore result."""
        result = RestoreResult(
            success=True,
            backup_id="test_id",
            files_restored=5,
            errors=[],
        )
        
        self.assertTrue(result.success)
        self.assertEqual(result.files_restored, 5)


class TestBackupManager(unittest.TestCase):
    """Test backup manager functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = TemporaryDirectory()
        self.backup_dir = Path(self.temp_dir.name) / "backups"
        self.manager = BackupManager(self.backup_dir)
    
    def tearDown(self):
        """Clean up test fixtures."""
        self.temp_dir.cleanup()
    
    def test_backup_config(self):
        """Test backing up configuration."""
        config_file = Path(self.temp_dir.name) / "config.json"
        config_file.write_text('{"model": "gpt-4"}')
        
        metadata = self.manager.backup_config(config_file)
        
        self.assertIsNotNone(metadata)
        self.assertEqual(metadata.backup_type, "config")
        self.assertTrue(metadata.compressed)
    
    def test_backup_history(self):
        """Test backing up history."""
        history_file = Path(self.temp_dir.name) / "history.json"
        history_file.write_text('{"messages": []}')
        
        metadata = self.manager.backup_history(history_file)
        
        self.assertIsNotNone(metadata)
        self.assertEqual(metadata.backup_type, "history")
    
    def test_backup_full(self):
        """Test full backup."""
        config_file = Path(self.temp_dir.name) / "config.json"
        config_file.write_text('{"model": "gpt-4"}')
        
        history_file = Path(self.temp_dir.name) / "history.json"
        history_file.write_text('{"messages": []}')
        
        models_file = Path(self.temp_dir.name) / "models.json"
        models_file.write_text('{"models": []}')
        
        metadata = self.manager.backup_full(config_file, history_file, models_file)
        
        self.assertIsNotNone(metadata)
        self.assertEqual(metadata.backup_type, "full")
    
    def test_restore_config(self):
        """Test restoring configuration."""
        config_file = Path(self.temp_dir.name) / "config.json"
        config_file.write_text('{"model": "gpt-4"}')
        
        # Create backup
        metadata = self.manager.backup_config(config_file)
        
        # Restore
        restore_path = Path(self.temp_dir.name) / "restore"
        result = self.manager.restore_config(metadata.backup_id, restore_path)
        
        self.assertTrue(result.success)
        self.assertGreater(result.files_restored, 0)
    
    def test_restore_history(self):
        """Test restoring history."""
        history_file = Path(self.temp_dir.name) / "history.json"
        history_file.write_text('{"messages": []}')
        
        # Create backup
        metadata = self.manager.backup_history(history_file)
        
        # Restore
        restore_path = Path(self.temp_dir.name) / "restore"
        result = self.manager.restore_history(metadata.backup_id, restore_path)
        
        self.assertTrue(result.success)
        self.assertGreater(result.files_restored, 0)
    
    def test_list_backups(self):
        """Test listing backups."""
        config_file = Path(self.temp_dir.name) / "config.json"
        config_file.write_text('{"model": "gpt-4"}')
        
        self.manager.backup_config(config_file)
        
        backups = self.manager.list_backups()
        
        self.assertGreater(len(backups), 0)
        self.assertEqual(backups[0].backup_type, "config")
    
    def test_delete_backup(self):
        """Test deleting a backup."""
        config_file = Path(self.temp_dir.name) / "config.json"
        config_file.write_text('{"model": "gpt-4"}')
        
        metadata = self.manager.backup_config(config_file)
        success = self.manager.delete_backup(metadata.backup_id)
        
        self.assertTrue(success)
    
    def test_restore_nonexistent_backup(self):
        """Test restoring a non-existent backup."""
        restore_path = Path(self.temp_dir.name) / "restore"
        result = self.manager.restore_config("nonexistent_id", restore_path)
        
        self.assertFalse(result.success)
        self.assertGreater(len(result.errors), 0)


class TestGlobalBackupManager(unittest.TestCase):
    """Test global backup manager instance."""

    def test_get_backup_manager(self):
        """Test getting global backup manager."""
        manager = get_backup_manager()
        self.assertIsNotNone(manager)
        
        # Should return same instance
        manager2 = get_backup_manager()
        self.assertIs(manager, manager2)


if __name__ == "__main__":
    unittest.main()
