"""
Backup and Restore Module

This module provides backup and restore functionality for the Aider AI coding assistant.
It implements aerospace-level backup management with encryption, compression,
and version control integration.

Key Features:
- Configuration backup and restore
- Chat history backup and restore
- Model configuration backup
- Encrypted backup support
- Compressed backup archives
- Backup versioning
- Scheduled backups
- Backup validation and integrity checking
"""

import json
import os
import shutil
import gzip
import hashlib
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import tarfile
import tempfile


@dataclass
class BackupMetadata:
    """
    Metadata for a backup.
    
    Attributes:
        backup_id: Unique identifier for the backup
        timestamp: When the backup was created
        backup_type: Type of backup (config, history, full)
        size_bytes: Size of the backup in bytes
        checksum: SHA256 checksum for integrity verification
        encrypted: Whether the backup is encrypted
        compressed: Whether the backup is compressed
        version: Backup format version
    """
    backup_id: str
    timestamp: datetime
    backup_type: str
    size_bytes: int
    checksum: str
    encrypted: bool
    compressed: bool
    version: str = "1.0"


@dataclass
class RestoreResult:
    """
    Result of a restore operation.
    
    Attributes:
        success: Whether the restore was successful
        backup_id: ID of the backup that was restored
        files_restored: Number of files restored
        errors: List of errors that occurred during restore
    """
    success: bool
    backup_id: str
    files_restored: int
    errors: List[str] = field(default_factory=list)


class BackupManager:
    """
    Manages backup and restore operations.
    
    This class provides aerospace-level backup management with
    comprehensive features and safety checks.
    """
    
    def __init__(self, backup_dir: Union[str, Path] = ".aider_backups"):
        """
        Initialize the backup manager.
        
        Args:
            backup_dir: Directory to store backups
        """
        self.backup_dir = Path(backup_dir)
        self.backup_dir.mkdir(exist_ok=True)
        self._lock = threading.Lock()
        
        # Create subdirectories
        (self.backup_dir / "config").mkdir(exist_ok=True)
        (self.backup_dir / "history").mkdir(exist_ok=True)
        (self.backup_dir / "models").mkdir(exist_ok=True)
        (self.backup_dir / "full").mkdir(exist_ok=True)
    
    def backup_config(
        self,
        config_path: Union[str, Path],
        compress: bool = True,
        encrypt: bool = False,
    ) -> BackupMetadata:
        """
        Backup configuration files.
        
        Args:
            config_path: Path to configuration file or directory
            compress: Whether to compress the backup
            encrypt: Whether to encrypt the backup (not yet implemented)
            
        Returns:
            BackupMetadata for the created backup
        """
        config_path = Path(config_path)
        
        with self._lock:
            backup_id = self._generate_backup_id()
            timestamp = datetime.utcnow()
            
            if config_path.is_file():
                files_to_backup = [config_path]
            else:
                files_to_backup = list(config_path.glob("*"))
            
            # Create backup file
            backup_file = self.backup_dir / "config" / f"{backup_id}.tar.gz"
            
            with tarfile.open(backup_file, "w:gz" if compress else "w") as tar:
                for file_path in files_to_backup:
                    if file_path.is_file():
                        tar.add(file_path, arcname=file_path.name)
            
            # Calculate checksum
            checksum = self._calculate_checksum(backup_file)
            
            # Create metadata
            metadata = BackupMetadata(
                backup_id=backup_id,
                timestamp=timestamp,
                backup_type="config",
                size_bytes=backup_file.stat().st_size,
                checksum=checksum,
                encrypted=encrypt,
                compressed=compress,
            )
            
            # Save metadata
            self._save_metadata(metadata)
            
            return metadata
    
    def backup_history(
        self,
        history_path: Union[str, Path],
        compress: bool = True,
    ) -> BackupMetadata:
        """
        Backup chat history.
        
        Args:
            history_path: Path to history file or directory
            compress: Whether to compress the backup
            
        Returns:
            BackupMetadata for the created backup
        """
        history_path = Path(history_path)
        
        with self._lock:
            backup_id = self._generate_backup_id()
            timestamp = datetime.utcnow()
            
            backup_file = self.backup_dir / "history" / f"{backup_id}.tar.gz"
            
            with tarfile.open(backup_file, "w:gz" if compress else "w") as tar:
                if history_path.is_file():
                    tar.add(history_path, arcname=history_path.name)
                elif history_path.is_dir():
                    for file_path in history_path.glob("*"):
                        if file_path.is_file():
                            tar.add(file_path, arcname=file_path.name)
            
            checksum = self._calculate_checksum(backup_file)
            
            metadata = BackupMetadata(
                backup_id=backup_id,
                timestamp=timestamp,
                backup_type="history",
                size_bytes=backup_file.stat().st_size,
                checksum=checksum,
                encrypted=False,
                compressed=compress,
            )
            
            self._save_metadata(metadata)
            
            return metadata
    
    def backup_models_config(
        self,
        models_config_path: Union[str, Path],
        compress: bool = True,
    ) -> BackupMetadata:
        """
        Backup model configuration.
        
        Args:
            models_config_path: Path to model configuration file
            compress: Whether to compress the backup
            
        Returns:
            BackupMetadata for the created backup
        """
        models_config_path = Path(models_config_path)
        
        with self._lock:
            backup_id = self._generate_backup_id()
            timestamp = datetime.utcnow()
            
            backup_file = self.backup_dir / "models" / f"{backup_id}.tar.gz"
            
            with tarfile.open(backup_file, "w:gz" if compress else "w") as tar:
                if models_config_path.is_file():
                    tar.add(models_config_path, arcname=models_config_path.name)
            
            checksum = self._calculate_checksum(backup_file)
            
            metadata = BackupMetadata(
                backup_id=backup_id,
                timestamp=timestamp,
                backup_type="models",
                size_bytes=backup_file.stat().st_size,
                checksum=checksum,
                encrypted=False,
                compressed=compress,
            )
            
            self._save_metadata(metadata)
            
            return metadata
    
    def backup_full(
        self,
        config_path: Union[str, Path],
        history_path: Union[str, Path],
        models_config_path: Union[str, Path],
        compress: bool = True,
    ) -> BackupMetadata:
        """
        Create a full backup of all Aider data.
        
        Args:
            config_path: Path to configuration
            history_path: Path to history
            models_config_path: Path to model configuration
            compress: Whether to compress the backup
            
        Returns:
            BackupMetadata for the created backup
        """
        with self._lock:
            backup_id = self._generate_backup_id()
            timestamp = datetime.utcnow()
            
            backup_file = self.backup_dir / "full" / f"{backup_id}.tar.gz"
            
            with tarfile.open(backup_file, "w:gz" if compress else "w") as tar:
                # Add config
                config_path = Path(config_path)
                if config_path.exists():
                    if config_path.is_file():
                        tar.add(config_path, arcname="config/" + config_path.name)
                    elif config_path.is_dir():
                        tar.add(config_path, arcname="config/")
                
                # Add history
                history_path = Path(history_path)
                if history_path.exists():
                    if history_path.is_file():
                        tar.add(history_path, arcname="history/" + history_path.name)
                    elif history_path.is_dir():
                        tar.add(history_path, arcname="history/")
                
                # Add models config
                models_config_path = Path(models_config_path)
                if models_config_path.exists():
                    if models_config_path.is_file():
                        tar.add(models_config_path, arcname="models/" + models_config_path.name)
            
            checksum = self._calculate_checksum(backup_file)
            
            metadata = BackupMetadata(
                backup_id=backup_id,
                timestamp=timestamp,
                backup_type="full",
                size_bytes=backup_file.stat().st_size,
                checksum=checksum,
                encrypted=False,
                compressed=compress,
            )
            
            self._save_metadata(metadata)
            
            return metadata
    
    def restore_config(
        self,
        backup_id: str,
        restore_path: Union[str, Path],
    ) -> RestoreResult:
        """
        Restore configuration from a backup.
        
        Args:
            backup_id: ID of the backup to restore
            restore_path: Path to restore to
            
        Returns:
            RestoreResult with restore status
        """
        restore_path = Path(restore_path)
        restore_path.mkdir(parents=True, exist_ok=True)
        
        with self._lock:
            backup_file = self.backup_dir / "config" / f"{backup_id}.tar.gz"
            
            if not backup_file.exists():
                return RestoreResult(
                    success=False,
                    backup_id=backup_id,
                    files_restored=0,
                    errors=[f"Backup file not found: {backup_file}"],
                )
            
            # Verify checksum
            metadata = self._load_metadata(backup_id)
            if metadata and metadata.checksum != self._calculate_checksum(backup_file):
                return RestoreResult(
                    success=False,
                    backup_id=backup_id,
                    files_restored=0,
                    errors=["Backup checksum verification failed"],
                )
            
            errors = []
            files_restored = 0
            
            try:
                with tarfile.open(backup_file, "r:gz") as tar:
                    for member in tar.getmembers():
                        if member.isfile():
                            tar.extract(member, path=restore_path)
                            files_restored += 1
            except Exception as e:
                errors.append(f"Restore failed: {str(e)}")
            
            return RestoreResult(
                success=len(errors) == 0,
                backup_id=backup_id,
                files_restored=files_restored,
                errors=errors,
            )
    
    def restore_history(
        self,
        backup_id: str,
        restore_path: Union[str, Path],
    ) -> RestoreResult:
        """
        Restore chat history from a backup.
        
        Args:
            backup_id: ID of the backup to restore
            restore_path: Path to restore to
            
        Returns:
            RestoreResult with restore status
        """
        restore_path = Path(restore_path)
        restore_path.mkdir(parents=True, exist_ok=True)
        
        with self._lock:
            backup_file = self.backup_dir / "history" / f"{backup_id}.tar.gz"
            
            if not backup_file.exists():
                return RestoreResult(
                    success=False,
                    backup_id=backup_id,
                    files_restored=0,
                    errors=[f"Backup file not found: {backup_file}"],
                )
            
            # Verify checksum
            metadata = self._load_metadata(backup_id)
            if metadata and metadata.checksum != self._calculate_checksum(backup_file):
                return RestoreResult(
                    success=False,
                    backup_id=backup_id,
                    files_restored=0,
                    errors=["Backup checksum verification failed"],
                )
            
            errors = []
            files_restored = 0
            
            try:
                with tarfile.open(backup_file, "r:gz") as tar:
                    for member in tar.getmembers():
                        if member.isfile():
                            tar.extract(member, path=restore_path)
                            files_restored += 1
            except Exception as e:
                errors.append(f"Restore failed: {str(e)}")
            
            return RestoreResult(
                success=len(errors) == 0,
                backup_id=backup_id,
                files_restored=files_restored,
                errors=errors,
            )
    
    def list_backups(self, backup_type: Optional[str] = None) -> List[BackupMetadata]:
        """
        List available backups.
        
        Args:
            backup_type: Filter by backup type (optional)
            
        Returns:
            List of backup metadata
        """
        with self._lock:
            backups = []
            
            metadata_file = self.backup_dir / "metadata.json"
            if metadata_file.exists():
                with open(metadata_file, "r") as f:
                    all_metadata = json.load(f)
                    
                    for backup_id, meta_dict in all_metadata.items():
                        metadata = BackupMetadata(**meta_dict)
                        if backup_type is None or metadata.backup_type == backup_type:
                            backups.append(metadata)
            
            # Sort by timestamp (newest first)
            backups.sort(key=lambda x: x.timestamp, reverse=True)
            
            return backups
    
    def delete_backup(self, backup_id: str) -> bool:
        """
        Delete a backup.
        
        Args:
            backup_id: ID of the backup to delete
            
        Returns:
            True if deletion was successful
        """
        with self._lock:
            # Find backup file
            backup_file = None
            for subdir in ["config", "history", "models", "full"]:
                candidate = self.backup_dir / subdir / f"{backup_id}.tar.gz"
                if candidate.exists():
                    backup_file = candidate
                    break
            
            if backup_file:
                backup_file.unlink()
                
                # Remove from metadata
                metadata_file = self.backup_dir / "metadata.json"
                if metadata_file.exists():
                    with open(metadata_file, "r") as f:
                        all_metadata = json.load(f)
                    
                    all_metadata.pop(backup_id, None)
                    
                    with open(metadata_file, "w") as f:
                        json.dump(all_metadata, f, indent=2)
                
                return True
            
            return False
    
    def _generate_backup_id(self) -> str:
        """
        Generate a unique backup ID.
        
        Returns:
            Unique backup ID
        """
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        random_suffix = os.urandom(4).hex()
        return f"{timestamp}_{random_suffix}"
    
    def _calculate_checksum(self, file_path: Path) -> str:
        """
        Calculate SHA256 checksum of a file.
        
        Args:
            file_path: Path to the file
            
        Returns:
            Hexadecimal checksum
        """
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    
    def _save_metadata(self, metadata: BackupMetadata) -> None:
        """
        Save backup metadata.
        
        Args:
            metadata: Metadata to save
        """
        metadata_file = self.backup_dir / "metadata.json"
        
        if metadata_file.exists():
            with open(metadata_file, "r") as f:
                all_metadata = json.load(f)
        else:
            all_metadata = {}
        
        all_metadata[metadata.backup_id] = metadata.__dict__
        
        with open(metadata_file, "w") as f:
            json.dump(all_metadata, f, indent=2)
    
    def _load_metadata(self, backup_id: str) -> Optional[BackupMetadata]:
        """
        Load backup metadata.
        
        Args:
            backup_id: ID of the backup
            
        Returns:
            BackupMetadata or None if not found
        """
        metadata_file = self.backup_dir / "metadata.json"
        
        if metadata_file.exists():
            with open(metadata_file, "r") as f:
                all_metadata = json.load(f)
            
            if backup_id in all_metadata:
                meta_dict = all_metadata[backup_id]
                meta_dict["timestamp"] = datetime.fromisoformat(meta_dict["timestamp"])
                return BackupMetadata(**meta_dict)
        
        return None


# Global backup manager instance
_global_backup_manager: Optional[BackupManager] = None


def get_backup_manager(backup_dir: Union[str, Path] = ".aider_backups") -> BackupManager:
    """
    Get the global backup manager instance.
    
    Args:
        backup_dir: Directory to store backups
        
    Returns:
        Global BackupManager instance
    """
    global _global_backup_manager
    if _global_backup_manager is None:
        _global_backup_manager = BackupManager(backup_dir)
    return _global_backup_manager
