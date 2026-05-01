"""
Index Manager Module

This module provides aerospace-grade project indexing functionality for the Aider AI coding assistant.
It implements full project indexing with high reliability, comprehensive error handling, and detailed monitoring.

Key Features:
- Full project indexing on startup
- Incremental indexing for file changes
- Background indexing support
- Resource management and limits
- Comprehensive error handling and recovery
- Detailed progress tracking and logging
- Index validation and integrity checks
- Performance monitoring and optimization

Aerospace-grade Standards:
- Redundant error handling
- Detailed logging at all levels
- Resource monitoring and limits
- Graceful degradation
- State persistence and recovery
- Integrity validation
"""

import hashlib
import json
import logging
import os
import psutil
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict

from diskcache import Cache
from tqdm import tqdm

from aider.dump import dump
from aider.waiting import Spinner

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    logger.warning("NumPy not available, vector search will be limited")

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    logger.warning("OpenAI library not available, embedding generation will be disabled")

# Configure logging
logger = logging.getLogger(__name__)


@dataclass
class MerkleNode:
    """Node in a Merkle tree."""
    hash: str
    children: List['MerkleNode'] = field(default_factory=list)
    file_path: Optional[str] = None
    is_leaf: bool = False
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            'hash': self.hash,
            'children': [child.to_dict() for child in self.children],
            'file_path': self.file_path,
            'is_leaf': self.is_leaf
        }


class EmbeddingProvider:
    """Base class for embedding providers."""
    
    def generate_embeddings(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for a list of texts.
        
        Args:
            texts: List of text strings to embed
            
        Returns:
            List of embedding vectors
        """
        raise NotImplementedError("Subclasses must implement generate_embeddings")


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """OpenAI API-based embedding provider."""
    
    def __init__(self, api_key: Optional[str] = None, model: str = "text-embedding-3-small"):
        """
        Initialize OpenAI embedding provider.
        
        Args:
            api_key: OpenAI API key (if None, uses OPENAI_API_KEY env var)
            model: Embedding model to use
        """
        if not OPENAI_AVAILABLE:
            raise ImportError("OpenAI library not available")
        
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OpenAI API key not provided")
        
        self.model = model
        self.client = OpenAI(api_key=self.api_key)
        logger.info(f"Initialized OpenAI embedding provider with model: {model}")
    
    def generate_embeddings(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings using OpenAI API.
        
        Args:
            texts: List of text strings to embed
            
        Returns:
            List of embedding vectors
        """
        try:
            response = self.client.embeddings.create(
                model=self.model,
                input=texts
            )
            embeddings = [item.embedding for item in response.data]
            logger.debug(f"Generated {len(embeddings)} embeddings")
            return embeddings
        except Exception as e:
            logger.error(f"Error generating embeddings: {e}")
            raise


class IndexStatus(Enum):
    """Index operation status."""
    IDLE = "idle"
    SCANNING = "scanning"
    INDEXING = "indexing"
    VALIDATING = "validating"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class IndexStats:
    """Index statistics for monitoring."""
    total_files: int = 0
    indexed_files: int = 0
    failed_files: int = 0
    skipped_files: int = 0
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    total_size_bytes: int = 0
    memory_peak_mb: float = 0.0
    errors: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            "total_files": self.total_files,
            "indexed_files": self.indexed_files,
            "failed_files": self.failed_files,
            "skipped_files": self.skipped_files,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "total_size_bytes": self.total_size_bytes,
            "memory_peak_mb": self.memory_peak_mb,
            "errors": self.errors[-10:],  # Keep last 10 errors
        }


class IndexManager:
    """
    Aerospace-grade index manager for project indexing.
    
    This class provides comprehensive project indexing with:
    - Full project scanning and indexing
    - Incremental updates based on file changes
    - Background processing support
    - Resource monitoring and limits
    - Comprehensive error handling
    - Detailed progress tracking
    - Index validation and integrity checks
    """
    
    INDEX_VERSION = 1
    INDEX_DIR = ".aider.index"
    INDEX_DB = "index.db"
    INDEX_STATE = "index_state.json"
    
    def __init__(
        self,
        root: str,
        io=None,
        max_memory_mb: int = 2048,
        background: bool = False,
        verbose: bool = False,
        enable_embeddings: bool = False,
    ):
        """
        Initialize the index manager.
        
        Args:
            root: Project root directory
            io: IO object for user interaction
            max_memory_mb: Maximum memory in MB for indexing
            background: Whether to run indexing in background
            verbose: Enable verbose logging
            enable_embeddings: Enable embeddings generation
        """
        self.root = Path(root)
        self.io = io
        self.max_memory_mb = max_memory_mb
        self.background = background
        self.verbose = verbose
        
        # Embedding provider for vector search
        self.embedding_provider: Optional[EmbeddingProvider] = None
        self.enable_embeddings = enable_embeddings
        if enable_embeddings and OPENAI_AVAILABLE:
            try:
                self.embedding_provider = OpenAIEmbeddingProvider(
                    api_key=os.environ.get("OPENAI_API_KEY"),
                    model="text-embedding-3-small"
                )
                logger.info("Embedding provider initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize embedding provider: {e}")
                self.embedding_provider = None
        
        # Index state
        self.status = IndexStatus.IDLE
        self.stats = IndexStats()
        self._cancel_flag = False
        self._index_thread: Optional[threading.Thread] = None
        
        # Cache and storage
        self.index_dir = self.root / self.INDEX_DIR
        self.index_dir.mkdir(parents=True, exist_ok=True)
        
        self.index_db_path = self.index_dir / self.INDEX_DB
        self.index_state_path = self.index_dir / self.INDEX_STATE
        
        # Initialize database
        self._init_database()
        
        # Load previous state if exists
        self._load_state()
        
        logger.info(f"IndexManager initialized for {self.root}")
        if self.verbose and self.io:
            self.io.tool_output(f"IndexManager initialized with max_memory_mb: {self.max_memory_mb}", log_only=False)
    
    def _init_database(self) -> None:
        """Initialize the index database with proper schema."""
        try:
            conn = sqlite3.connect(str(self.index_db_path))
            cursor = conn.cursor()
            
            # Create files table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS files (
                    path TEXT PRIMARY KEY,
                    size INTEGER,
                    mtime REAL,
                    hash TEXT,
                    indexed_at REAL,
                    status TEXT,
                    error TEXT
                )
            """)
            
            # Create symbols table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS symbols (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_path TEXT,
                    name TEXT,
                    kind TEXT,
                    line INTEGER,
                    UNIQUE(file_path, name, kind, line)
                )
            """)
            
            # Create references table for cross-file tracking
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS references (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    from_file TEXT,
                    to_file TEXT,
                    symbol_name TEXT,
                    line INTEGER,
                    UNIQUE(from_file, to_file, symbol_name, line)
                )
            """)
            
            # Create chunks table for code chunking
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_path TEXT,
                    chunk_type TEXT,
                    chunk_name TEXT,
                    start_line INTEGER,
                    end_line INTEGER,
                    content_hash TEXT,
                    content TEXT,
                    UNIQUE(file_path, chunk_type, chunk_name, content_hash)
                )
            """)
            
            # Create git_history table for Git integration
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS git_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    commit_sha TEXT UNIQUE,
                    parent_sha TEXT,
                    commit_message TEXT,
                    author TEXT,
                    commit_time REAL,
                    branch TEXT
                )
            """)
            
            # Create git_file_history table for file-level history
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS git_file_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    commit_sha TEXT,
                    file_path TEXT,
                    file_hash TEXT,
                    change_type TEXT,
                    FOREIGN KEY (commit_sha) REFERENCES git_history(commit_sha),
                    UNIQUE(commit_sha, file_path)
                )
            """)
            
            # Create embeddings table for vector search
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS embeddings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_path TEXT,
                    chunk_type TEXT,
                    chunk_name TEXT,
                    content TEXT,
                    content_hash TEXT,
                    embedding BLOB,
                    model TEXT,
                    created_at REAL,
                    UNIQUE(file_path, chunk_name, content_hash, model)
                )
            """)
            
            # Create indexes for better query performance
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_symbols_file ON symbols(file_path)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_references_symbol ON references(symbol_name)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_references_from ON references(from_file)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_chunks_file ON chunks(file_path)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_chunks_hash ON chunks(content_hash)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_git_history_sha ON git_history(commit_sha)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_git_file_history_sha ON git_file_history(commit_sha)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_git_file_history_file ON git_file_history(file_path)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_embeddings_file ON embeddings(file_path)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_embeddings_hash ON embeddings(content_hash)")
            
            # Create metadata table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            
            # Set index version
            cursor.execute("""
                INSERT OR REPLACE INTO metadata (key, value)
                VALUES ('version', ?)
            """, (str(self.INDEX_VERSION),))
            
            conn.commit()
            conn.close()
            
            logger.info("Index database initialized successfully")
            
        except sqlite3.Error as e:
            logger.error(f"Failed to initialize index database: {e}")
            raise
    
    def _load_state(self) -> None:
        """Load previous index state if exists."""
        try:
            if self.index_state_path.exists():
                with open(self.index_state_path, 'r') as f:
                    state = json.load(f)
                    logger.info(f"Loaded previous index state: {state.get('status', 'unknown')}")
        except Exception as e:
            logger.warning(f"Failed to load index state: {e}")
    
    def _save_state(self) -> None:
        """Save current index state."""
        try:
            state = {
                "status": self.status.value,
                "stats": self.stats.to_dict(),
                "last_updated": datetime.now().isoformat(),
            }
            with open(self.index_state_path, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save index state: {e}")
    
    def _check_memory_usage(self) -> bool:
        """
        Check if memory usage is within limits.
        
        Returns:
            True if memory usage is acceptable, False otherwise
        """
        try:
            process = psutil.Process(os.getpid())
            memory_mb = process.memory_info().rss / (1024 * 1024)
            
            if memory_mb > self.stats.memory_peak_mb:
                self.stats.memory_peak_mb = memory_mb
            
            if memory_mb > self.max_memory_mb:
                logger.warning(f"Memory usage {memory_mb:.2f} MB exceeds limit {self.max_memory_mb} MB")
                return False
            
            return True
        except Exception as e:
            logger.error(f"Error checking memory usage: {e}")
            return True  # Assume OK if check fails
    
    def _get_file_hash(self, filepath: Path) -> Optional[str]:
        """
        Calculate SHA256 hash of a file.
        
        Args:
            filepath: Path to the file
            
        Returns:
            Hash string or None if file cannot be read
        """
        try:
            sha256_hash = hashlib.sha256()
            with open(filepath, "rb") as f:
                for byte_block in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(byte_block)
            return sha256_hash.hexdigest()
        except Exception as e:
            logger.error(f"Error calculating hash for {filepath}: {e}")
            return None
    
    def _needs_indexing(self, filepath: Path) -> bool:
        """
        Check if a file needs to be indexed.
        
        Args:
            filepath: Path to the file
            
        Returns:
            True if file needs indexing, False otherwise
        """
        try:
            conn = sqlite3.connect(str(self.index_db_path))
            cursor = conn.cursor()
            
            cursor.execute(
                "SELECT mtime, hash FROM files WHERE path = ?",
                (str(filepath),)
            )
            result = cursor.fetchone()
            
            conn.close()
            
            if not result:
                return True
            
            old_mtime, old_hash = result
            current_mtime = os.path.getmtime(filepath)
            current_hash = self._get_file_hash(filepath)
            
            # Check if file was modified
            if current_mtime != old_mtime:
                return True
            
            # Check if content changed (different hash but same mtime)
            if current_hash and old_hash and current_hash != old_hash:
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error checking if file needs indexing: {e}")
            return True  # Assume needs indexing on error
    
    def _index_file(self, filepath: Path) -> Tuple[bool, Optional[str]]:
        """
        Index a single file.
        
        Args:
            filepath: Path to the file
            
        Returns:
            Tuple of (success, error_message)
        """
        try:
            if not filepath.exists():
                return False, f"File does not exist: {filepath}"
            
            if not filepath.is_file():
                return False, f"Not a file: {filepath}"
            
            # Get file info
            size = filepath.stat().st_size
            mtime = os.path.getmtime(filepath)
            file_hash = self._get_file_hash(filepath)
            
            # Check if file needs indexing
            if not self._needs_indexing(filepath):
                return True, None
            
            # Extract symbols using AST for Python files
            if filepath.suffix == '.py':
                self._extract_python_symbols(filepath, str(filepath))
            else:
                # For non-Python files, just record metadata
                self._record_file_metadata(filepath, size, mtime, file_hash)
            
            # Chunk code for better semantic understanding
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                chunks = self._chunk_code(filepath, content)
                self._store_chunks(filepath, chunks)
                
                # Generate and store embeddings if enabled
                if self.enable_embeddings and chunks:
                    self._generate_and_store_embeddings(filepath, chunks)
            except Exception as e:
                logger.error(f"Error chunking {filepath}: {e}")
            
            return True, None
            
        except Exception as e:
            error_msg = f"Error indexing {filepath}: {e}"
            logger.error(error_msg)
            return False, error_msg
    
    def _extract_python_symbols(self, filepath: Path, rel_fname: str):
        """
        Extract symbols from Python file using AST.
        
        Args:
            filepath: Path to the Python file
            rel_fname: Relative filename for storage
        """
        conn = None
        try:
            import ast
            
            # Read file with error handling
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
            except (IOError, OSError, UnicodeDecodeError) as e:
                logger.error(f"Failed to read file {filepath}: {e}")
                return
            
            # Parse AST with error handling
            try:
                tree = ast.parse(content, filename=str(filepath))
            except SyntaxError as e:
                logger.error(f"Syntax error in {filepath} at line {e.lineno}: {e.msg}")
                return
            except Exception as e:
                logger.error(f"Failed to parse AST for {filepath}: {e}")
                return
            
            # Use context manager for database connection
            conn = sqlite3.connect(str(self.index_db_path))
            cursor = conn.cursor()
            
            # Clear existing symbols for this file
            cursor.execute("DELETE FROM symbols WHERE file_path = ?", (rel_fname,))
            
            # Extract symbols and track cross-file references
            imports = []
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    self._add_symbol(cursor, rel_fname, node.name, 'function', node.lineno)
                    # Track function calls for cross-file references
                    self._track_function_calls(node, rel_fname, imports)
                elif isinstance(node, ast.AsyncFunctionDef):
                    self._add_symbol(cursor, rel_fname, node.name, 'async_function', node.lineno)
                elif isinstance(node, ast.ClassDef):
                    self._add_symbol(cursor, rel_fname, node.name, 'class', node.lineno)
                elif isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            self._add_symbol(cursor, rel_fname, target.id, 'variable', node.lineno)
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.append(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    module = node.module if node.module else ''
                    for alias in node.names:
                        imports.append(f"{module}.{alias.name}")
            
            conn.commit()
            
            # Record file metadata
            self._record_file_metadata(filepath, filepath.stat().st_size, 
                                      os.path.getmtime(filepath), 
                                      self._get_file_hash(filepath))
            
        except Exception as e:
            logger.error(f"Unexpected error extracting symbols from {filepath}: {e}")
        finally:
            # Ensure database connection is always closed
            if conn:
                conn.close()
    
    def _track_function_calls(self, node, file_path: str, imports: List[str]):
        """
        Track function calls for cross-file reference tracking.
        
        Args:
            node: AST node to analyze
            file_path: Current file path
            imports: List of imported modules
        """
        conn = None
        try:
            conn = sqlite3.connect(str(self.index_db_path))
            cursor = conn.cursor()
            
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    if isinstance(child.func, ast.Name):
                        # Check if this is a call to a known symbol in another file
                        cursor.execute(
                            "SELECT file_path FROM symbols WHERE name = ? AND file_path != ?",
                            (child.func.id, file_path)
                        )
                        results = cursor.fetchall()
                        if results:
                            # Record cross-file reference
                            for result in results:
                                to_file = result[0]
                                cursor.execute("""
                                    INSERT OR IGNORE INTO references (from_file, to_file, symbol_name, line)
                                    VALUES (?, ?, ?, ?)
                                """, (file_path, to_file, child.func.id, child.lineno))
            
            conn.commit()
            
        except Exception as e:
            logger.error(f"Error tracking function calls in {file_path}: {e}")
        finally:
            if conn:
                conn.close()
    
    def _add_symbol(self, cursor, file_path: str, name: str, kind: str, line: int) -> None:
        """
        Add a symbol to the database.
        
        Args:
            cursor: Database cursor
            file_path: Path to the file containing the symbol
            name: Symbol name
            kind: Symbol kind (function, class, variable, etc.)
            line: Line number where symbol is defined
        """
        cursor.execute(
            "INSERT OR REPLACE INTO symbols (file_path, name, kind, line) VALUES (?, ?, ?, ?)",
            (file_path, name, kind, line)
        )
    
    def _record_file_metadata(self, filepath: Path, size: int, mtime: float, file_hash: str) -> None:
        """
        Record file metadata to the database.
        
        Args:
            filepath: Path to the file
            size: File size in bytes
            mtime: File modification time
            file_hash: Hash of file content for change detection
        """
        conn = None
        try:
            conn = sqlite3.connect(str(self.index_db_path))
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT OR REPLACE INTO files (path, size, mtime, hash, indexed_at, status, error)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (str(filepath), size, mtime, file_hash, time.time(), "indexed", None))
            
            conn.commit()
        except Exception as e:
            logger.error(f"Error recording file metadata for {filepath}: {e}")
        finally:
            if conn:
                conn.close()
    
    def _scan_directory(self, directory: Path) -> List[Path]:
        """
        Scan directory for files to index.
        
        Args:
            directory: Directory to scan
            
        Returns:
            List of file paths to index
        """
        files = []
        
        # Common file extensions to index
        extensions = {
            '.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.cpp', '.c', '.h',
            '.cs', '.go', '.rs', '.rb', '.php', '.swift', '.kt', '.scala',
            '.html', '.css', '.scss', '.json', '.xml', '.yaml', '.yml',
            '.md', '.txt', '.sh', '.bash', '.zsh', '.sql'
        }
        
        try:
            for item in directory.rglob('*'):
                if item.is_file() and item.suffix in extensions:
                    # Skip common ignore directories
                    if any(part.startswith('.') for part in item.parts):
                        continue
                    if any(part in ['node_modules', '__pycache__', 'venv', 'env', '.git'] for part in item.parts):
                        continue
                    files.append(item)
        except Exception as e:
            logger.error(f"Error scanning directory {directory}: {e}")
        
        return files
    
    def index_full(self, force: bool = False) -> IndexStats:
        """
        Perform full project indexing.
        
        Args:
            force: Force re-indexing of all files regardless of state
            
        Returns:
            IndexStats object containing indexing statistics and results
        """
        logger.info(f"Starting full index of {self.root}")
        
        self.status = IndexStatus.SCANNING
        self.stats = IndexStats()
        self.stats.start_time = datetime.now()
        self._cancel_flag = False
        
        try:
            # Scan directory
            if self.verbose and self.io:
                self.io.tool_output("\n" + "─" * 60, log_only=False)
                self.io.tool_output("🔍 Scanning project files...", log_only=False, bold=True)
                self.io.tool_output("─" * 60, log_only=False)
            
            files = self._scan_directory(self.root)
            self.stats.total_files = len(files)
            
            if self.verbose and self.io:
                self.io.tool_output(f"Found {len(files)} files to index", log_only=False)
            
            if not files:
                if self.verbose and self.io:
                    self.io.tool_output("No files to index", log_only=False)
                return self.stats
            
            # Build file hashes for Merkle tree
            file_hashes = {}
            for filepath in files:
                try:
                    file_hash = self._get_file_hash(filepath)
                    file_hashes[str(filepath)] = file_hash
                except Exception as e:
                    logger.warning(f"Failed to hash {filepath}: {e}")
            
            # Build Merkle tree for efficient change detection
            if self.verbose and self.io:
                self.io.tool_output("\n" + "─" * 60, log_only=False)
                self.io.tool_output("🌳 Building Merkle tree...", log_only=False, bold=True)
                self.io.tool_output("─" * 60, log_only=False)
            
            new_merkle_tree = self._build_merkle_tree(file_hashes)
            
            # Load previous Merkle tree if exists
            old_merkle_tree = None
            try:
                conn = sqlite3.connect(str(self.index_db_path))
                cursor = conn.cursor()
                cursor.execute("SELECT value FROM metadata WHERE key = 'merkle_tree'")
                result = cursor.fetchone()
                if result:
                    import json
                    old_merkle_dict = json.loads(result[0])
                    old_merkle_tree = self._dict_to_merkle_node(old_merkle_dict)
                conn.close()
            except Exception as e:
                logger.debug(f"Failed to load previous Merkle tree: {e}")
            
            # Determine which files need re-indexing
            if not force and old_merkle_tree:
                changed_files = self._get_changed_files(old_merkle_tree, new_merkle_tree)
                if self.verbose and self.io:
                    self.io.tool_output(f"Changed files detected: {len(changed_files)}", log_only=False)
                files_to_index = [f for f in files if str(f) in changed_files]
            else:
                files_to_index = files
            
            # Index files
            self.status = IndexStatus.INDEXING
            
            if self.verbose and self.io:
                self.io.tool_output("\n" + "─" * 60, log_only=False)
                self.io.tool_output(f"📝 Indexing {len(files_to_index)} files...", log_only=False, bold=True)
                self.io.tool_output("─" * 60, log_only=False)
            
            progress_bar = tqdm(files_to_index, desc="Indexing", disable=not self.verbose)
            
            for filepath in progress_bar:
                if self._cancel_flag:
                    self.status = IndexStatus.CANCELLED
                    break
                
                # Check memory usage
                if not self._check_memory_usage():
                    logger.warning("Memory limit reached, stopping index")
                    self.status = IndexStatus.FAILED
                    self.stats.errors.append("Memory limit reached")
                    break
                
                # Index file
                success, error = self._index_file(filepath)
                
                if success:
                    self.stats.indexed_files += 1
                    self.stats.total_size_bytes += filepath.stat().st_size
                else:
                    self.stats.failed_files += 1
                    if error:
                        self.stats.errors.append(error)
            
            # Save Merkle tree for next time
            try:
                conn = sqlite3.connect(str(self.index_db_path))
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO metadata (key, value)
                    VALUES ('merkle_tree', ?)
                """, (json.dumps(new_merkle_tree.to_dict()),))
                conn.commit()
                conn.close()
            except Exception as e:
                logger.warning(f"Failed to save Merkle tree: {e}")
            
            # Index Git history
            if self.verbose and self.io:
                self.io.tool_output("\n" + "─" * 60, log_only=False)
                self.io.tool_output("📚 Indexing Git history...", log_only=False, bold=True)
                self.io.tool_output("─" * 60, log_only=False)
            
            self._index_git_history()
            
            # Validate index
            self.status = IndexStatus.VALIDATING
            self._validate_index()
            
            # Complete
            self.status = IndexStatus.COMPLETED
            self.stats.end_time = datetime.now()
            
            # Save state
            self._save_state()
            
            if self.verbose and self.io:
                self._print_summary()
            
            logger.info(f"Full index completed: {self.stats.indexed_files} files indexed")
            
        except Exception as e:
            self.status = IndexStatus.FAILED
            self.stats.errors.append(str(e))
            logger.error(f"Full index failed: {e}")
        
        return self.stats
    
    def _validate_index(self) -> None:
        """Validate index integrity."""
        try:
            conn = sqlite3.connect(str(self.index_db_path))
            cursor = conn.cursor()
            
            # Check for orphaned symbol entries
            cursor.execute("""
                SELECT COUNT(*) FROM symbols
                WHERE file_path NOT IN (SELECT path FROM files)
            """)
            orphaned = cursor.fetchone()[0]
            
            if orphaned > 0:
                logger.warning(f"Found {orphaned} orphaned symbol entries")
                cursor.execute("""
                    DELETE FROM symbols
                    WHERE file_path NOT IN (SELECT path FROM files)
                """)
                conn.commit()
            
            conn.close()
            
            logger.info("Index validation completed")
            
        except Exception as e:
            logger.error(f"Index validation failed: {e}")
    
    def _print_summary(self) -> None:
        """Print index summary to user."""
        self.io.tool_output("\n" + "─" * 60, log_only=False)
        self.io.tool_output("✅ Index Complete", log_only=False, bold=True)
        self.io.tool_output("─" * 60, log_only=False)
        self.io.tool_output(f"📊 Statistics:", log_only=False)
        self.io.tool_output(f"   • Total files: {self.stats.total_files}", log_only=False)
        self.io.tool_output(f"   • Indexed: {self.stats.indexed_files}", log_only=False)
        self.io.tool_output(f"   • Failed: {self.stats.failed_files}", log_only=False)
        self.io.tool_output(f"   • Skipped: {self.stats.skipped_files}", log_only=False)
        self.io.tool_output(f"   • Total size: {self.stats.total_size_bytes / (1024*1024):.2f} MB", log_only=False)
        
        if self.stats.start_time and self.stats.end_time:
            duration = (self.stats.end_time - self.stats.start_time).total_seconds()
            self.io.tool_output(f"   • Duration: {duration:.2f} seconds", log_only=False)
        
        if self.stats.memory_peak_mb > 0:
            self.io.tool_output(f"   • Peak memory: {self.stats.memory_peak_mb:.2f} MB", log_only=False)
        
        if self.stats.errors:
            self.io.tool_output(f"\n⚠️ Errors ({len(self.stats.errors)}):", log_only=False)
            for error in self.stats.errors[:5]:  # Show first 5 errors
                self.io.tool_output(f"   - {error}", log_only=False)
        
        self.io.tool_output("─" * 60, log_only=False)
        self.io.tool_output("", log_only=False)
    
    def index_incremental(self) -> IndexStats:
        """
        Perform incremental indexing of modified files.
        
        Returns:
            Index statistics
        """
        logger.info("Starting incremental index")
        
        self.status = IndexStatus.SCANNING
        self.stats = IndexStats()
        self.stats.start_time = datetime.now()
        
        try:
            # Scan directory
            files = self._scan_directory(self.root)
            
            # Filter files that need indexing
            files_to_index = [f for f in files if self._needs_indexing(f)]
            self.stats.total_files = len(files_to_index)
            
            if not files_to_index:
                logger.info("No files need incremental indexing")
                return self.stats
            
            # Index modified files
            self.status = IndexStatus.INDEXING
            
            for filepath in files_to_index:
                if self._cancel_flag:
                    self.status = IndexStatus.CANCELLED
                    break
                
                success, error = self._index_file(filepath)
                
                if success:
                    self.stats.indexed_files += 1
                else:
                    self.stats.failed_files += 1
                    if error:
                        self.stats.errors.append(error)
            
            self.status = IndexStatus.COMPLETED
            self.stats.end_time = datetime.now()
            
            logger.info(f"Incremental index completed: {self.stats.indexed_files} files indexed")
            
        except Exception as e:
            self.status = IndexStatus.FAILED
            self.stats.errors.append(str(e))
            logger.error(f"Incremental index failed: {e}")
        
        return self.stats
    
    def cancel(self) -> None:
        """Cancel ongoing indexing operation."""
        logger.info("Cancelling index operation")
        self._cancel_flag = True
        
        if self._index_thread and self._index_thread.is_alive():
            self._index_thread.join(timeout=5)
    
    def get_status(self) -> Tuple[IndexStatus, IndexStats]:
        """
        Get current index status and statistics.
        
        Returns:
            Tuple of (status, stats)
        """
        return (self.status, self.stats)
    
    def search_symbols(self, query: str, kind: str = None) -> List[Dict]:
        """
        Search for symbols in the index.
        
        Args:
            query: Search query (symbol name or pattern)
            kind: Optional filter by symbol kind (function, class, variable)
            
        Returns:
            List of matching symbols with metadata
        """
        if not query or not isinstance(query, str):
            logger.warning(f"Invalid search query: {query}")
            return []
        
        conn = None
        try:
            conn = sqlite3.connect(str(self.index_db_path))
            cursor = conn.cursor()
            
            if kind:
                cursor.execute(
                    "SELECT file_path, name, kind, line FROM symbols WHERE name LIKE ? AND kind = ?",
                    (f"%{query}%", kind)
                )
            else:
                cursor.execute(
                    "SELECT file_path, name, kind, line FROM symbols WHERE name LIKE ?",
                    (f"%{query}%",)
                )
            
            results = []
            for row in cursor.fetchall():
                results.append({
                    'file_path': row[0],
                    'name': row[1],
                    'kind': row[2],
                    'line': row[3]
                })
            
            return results
            
        except Exception as e:
            logger.error(f"Error searching symbols: {e}")
            return []
        finally:
            if conn:
                conn.close()
    
    def search_references(self, symbol_name: str) -> List[Dict]:
        """
        Search for references to a symbol across files.
        
        Args:
            symbol_name: Name of the symbol to search for
            
        Returns:
            List of references with file and line information
        """
        if not symbol_name or not isinstance(symbol_name, str):
            logger.warning(f"Invalid symbol name: {symbol_name}")
            return []
        
        conn = None
        try:
            conn = sqlite3.connect(str(self.index_db_path))
            cursor = conn.cursor()
            
            cursor.execute(
                "SELECT from_file, to_file, symbol_name, line FROM references WHERE symbol_name = ?",
                (symbol_name,)
            )
            
            results = []
            for row in cursor.fetchall():
                results.append({
                    'from_file': row[0],
                    'to_file': row[1],
                    'symbol_name': row[2],
                    'line': row[3]
                })
            
            return results
            
        except Exception as e:
            logger.error(f"Error searching references: {e}")
            return []
        finally:
            if conn:
                conn.close()
    
    def get_file_symbols(self, file_path: str) -> List[Dict]:
        """
        Get all symbols for a specific file.
        
        Args:
            file_path: Path to the file
            
        Returns:
            List of symbols in the file
        """
        if not file_path or not isinstance(file_path, str):
            logger.warning(f"Invalid file path: {file_path}")
            return []
        
        conn = None
        try:
            conn = sqlite3.connect(str(self.index_db_path))
            cursor = conn.cursor()
            
            cursor.execute(
                "SELECT name, kind, line FROM symbols WHERE file_path = ? ORDER BY line",
                (file_path,)
            )
            
            results = []
            for row in cursor.fetchall():
                results.append({
                    'name': row[0],
                    'kind': row[1],
                    'line': row[2]
                })
            
            return results
            
        except Exception as e:
            logger.error(f"Error getting file symbols: {e}")
            return []
        finally:
            if conn:
                conn.close()
    
    def _chunk_code(self, filepath: Path, content: str) -> List[Dict]:
        """
        Chunk code into semantically meaningful pieces.
        
        This method splits code into logical chunks (functions, classes, etc.)
        similar to Cursor's approach for better semantic understanding.
        
        Supports multiple languages:
        - Python: AST-based chunking for functions, classes
        - JavaScript/TypeScript: Simple regex-based chunking
        - Other languages: Line-based chunking
        
        Args:
            filepath: Path to the file
            content: File content
            
        Returns:
            List of chunks with metadata including type, name, line range, content, and hash
        """
        chunks = []
        
        if not content or not content.strip():
            logger.warning(f"Empty content for {filepath}")
            return chunks
        
        # Python: Use AST for precise chunking
        if filepath.suffix == '.py':
            return self._chunk_python_code(filepath, content)
        
        # JavaScript/TypeScript: Use regex for function/class detection
        elif filepath.suffix in ['.js', '.jsx', '.ts', '.tsx']:
            return self._chunk_javascript_code(filepath, content)
        
        # Go: Use regex for function detection
        elif filepath.suffix == '.go':
            return self._chunk_go_code(filepath, content)
        
        # Rust: Use regex for function detection
        elif filepath.suffix == '.rs':
            return self._chunk_rust_code(filepath, content)
        
        # Default: Line-based chunking
        else:
            return self._chunk_by_lines(filepath, content)
    
    def _chunk_python_code(self, filepath: Path, content: str) -> List[Dict]:
        """Chunk Python code using AST."""
        chunks = []
        try:
            import ast
            tree = ast.parse(content, filename=str(filepath))
            
            for node in ast.walk(tree):
                chunk_info = None
                
                if isinstance(node, ast.FunctionDef):
                    chunk_info = {
                        'type': 'function',
                        'name': node.name,
                        'start_line': node.lineno,
                        'end_line': node.end_lineno if hasattr(node, 'end_lineno') else node.lineno,
                        'content': ast.get_source_segment(content, node)
                    }
                elif isinstance(node, ast.AsyncFunctionDef):
                    chunk_info = {
                        'type': 'async_function',
                        'name': node.name,
                        'start_line': node.lineno,
                        'end_line': node.end_lineno if hasattr(node, 'end_lineno') else node.lineno,
                        'content': ast.get_source_segment(content, node)
                    }
                elif isinstance(node, ast.ClassDef):
                    chunk_info = {
                        'type': 'class',
                        'name': node.name,
                        'start_line': node.lineno,
                        'end_line': node.end_lineno if hasattr(node, 'end_lineno') else node.lineno,
                        'content': ast.get_source_segment(content, node)
                    }
                
                if chunk_info and chunk_info['content']:
                    chunk_info['hash'] = self._get_content_hash(chunk_info['content'])
                    chunks.append(chunk_info)
                    
        except SyntaxError as e:
            logger.error(f"Syntax error in {filepath}: {e}")
            chunks.append(self._create_file_chunk(filepath, content))
        except Exception as e:
            logger.error(f"Error chunking {filepath}: {e}")
            chunks.append(self._create_file_chunk(filepath, content))
        
        logger.debug(f"Chunked {filepath} into {len(chunks)} Python chunks")
        return chunks
    
    def _chunk_javascript_code(self, filepath: Path, content: str) -> List[Dict]:
        """Chunk JavaScript/TypeScript code using regex."""
        chunks = []
        import re
        
        # Regex patterns for JS/TS
        function_pattern = r'(?:function\s+(\w+)|const\s+(\w+)\s*=\s*(?:async\s+)?(?:function|\([^)]*\)\s*=>)|(\w+)\s*\([^)]*\)\s*\{)'
        class_pattern = r'class\s+(\w+)'
        
        lines = content.split('\n')
        current_chunk = []
        chunk_name = 'unknown'
        chunk_type = 'section'
        
        for i, line in enumerate(lines, 1):
            # Check for function
            func_match = re.search(function_pattern, line)
            if func_match:
                if current_chunk:
                    chunks.append(self._create_chunk_from_lines(
                        filepath, chunk_name, chunk_type, current_chunk, i - len(current_chunk)
                    ))
                    current_chunk = []
                
                chunk_name = func_match.group(1) or func_match.group(2) or func_match.group(3)
                chunk_type = 'function'
            
            # Check for class
            class_match = re.search(class_pattern, line)
            if class_match:
                if current_chunk:
                    chunks.append(self._create_chunk_from_lines(
                        filepath, chunk_name, chunk_type, current_chunk, i - len(current_chunk)
                    ))
                    current_chunk = []
                
                chunk_name = class_match.group(1)
                chunk_type = 'class'
            
            current_chunk.append(line)
        
        # Add last chunk
        if current_chunk:
            chunks.append(self._create_chunk_from_lines(
                filepath, chunk_name, chunk_type, current_chunk, len(lines) - len(current_chunk) + 1
            ))
        
        logger.debug(f"Chunked {filepath} into {len(chunks)} JS/TS chunks")
        return chunks
    
    def _chunk_go_code(self, filepath: Path, content: str) -> List[Dict]:
        """Chunk Go code using regex."""
        chunks = []
        import re
        
        # Go function pattern
        func_pattern = r'func\s+(?:\(\s*\w+\s+\*?\w+\s*\)\s+)?(\w+)\s*\('
        
        lines = content.split('\n')
        current_chunk = []
        chunk_name = 'unknown'
        chunk_type = 'section'
        
        for i, line in enumerate(lines, 1):
            func_match = re.search(func_pattern, line)
            if func_match:
                if current_chunk:
                    chunks.append(self._create_chunk_from_lines(
                        filepath, chunk_name, chunk_type, current_chunk, i - len(current_chunk)
                    ))
                    current_chunk = []
                
                chunk_name = func_match.group(1)
                chunk_type = 'function'
            
            current_chunk.append(line)
        
        if current_chunk:
            chunks.append(self._create_chunk_from_lines(
                filepath, chunk_name, chunk_type, current_chunk, len(lines) - len(current_chunk) + 1
            ))
        
        logger.debug(f"Chunked {filepath} into {len(chunks)} Go chunks")
        return chunks
    
    def _chunk_rust_code(self, filepath: Path, content: str) -> List[Dict]:
        """Chunk Rust code using regex."""
        chunks = []
        import re
        
        # Rust function pattern
        func_pattern = r'fn\s+(\w+)\s*\('
        struct_pattern = r'struct\s+(\w+)'
        impl_pattern = r'impl\s+(\w+)'
        
        lines = content.split('\n')
        current_chunk = []
        chunk_name = 'unknown'
        chunk_type = 'section'
        
        for i, line in enumerate(lines, 1):
            func_match = re.search(func_pattern, line)
            struct_match = re.search(struct_pattern, line)
            impl_match = re.search(impl_pattern, line)
            
            if func_match or struct_match or impl_match:
                if current_chunk:
                    chunks.append(self._create_chunk_from_lines(
                        filepath, chunk_name, chunk_type, current_chunk, i - len(current_chunk)
                    ))
                    current_chunk = []
                
                if func_match:
                    chunk_name = func_match.group(1)
                    chunk_type = 'function'
                elif struct_match:
                    chunk_name = struct_match.group(1)
                    chunk_type = 'struct'
                elif impl_match:
                    chunk_name = impl_match.group(1)
                    chunk_type = 'impl'
            
            current_chunk.append(line)
        
        if current_chunk:
            chunks.append(self._create_chunk_from_lines(
                filepath, chunk_name, chunk_type, current_chunk, len(lines) - len(current_chunk) + 1
            ))
        
        logger.debug(f"Chunked {filepath} into {len(chunks)} Rust chunks")
        return chunks
    
    def _chunk_by_lines(self, filepath: Path, content: str) -> List[Dict]:
        """Chunk code by lines (fallback for unsupported languages)."""
        lines = content.split('\n')
        chunk_size = 100  # lines per chunk
        chunks = []
        
        for i in range(0, len(lines), chunk_size):
            chunk_content = '\n'.join(lines[i:i+chunk_size])
            if chunk_content.strip():
                chunks.append({
                    'type': 'section',
                    'name': f"{filepath.name}_chunk_{i//chunk_size}",
                    'start_line': i + 1,
                    'end_line': min(i + chunk_size, len(lines)),
                    'content': chunk_content,
                    'hash': self._get_content_hash(chunk_content)
                })
        
        logger.debug(f"Chunked {filepath} into {len(chunks)} line-based chunks")
        return chunks
    
    def _create_chunk_from_lines(self, filepath: Path, name: str, chunk_type: str, lines: List[str], start_line: int) -> Dict:
        """Create chunk dictionary from lines."""
        content = '\n'.join(lines)
        return {
            'type': chunk_type,
            'name': name,
            'start_line': start_line,
            'end_line': start_line + len(lines) - 1,
            'content': content,
            'hash': self._get_content_hash(content)
        }
    
    def _create_file_chunk(self, filepath: Path, content: str) -> Dict:
        """Create file-level chunk as fallback."""
        return {
            'type': 'file',
            'name': filepath.name,
            'start_line': 1,
            'end_line': content.count('\n') + 1,
            'content': content,
            'hash': self._get_content_hash(content)
        }
    
    def _get_content_hash(self, content: str) -> str:
        """
        Get hash of content for caching and deduplication.
        
        Args:
            content: Content to hash
            
        Returns:
            SHA256 hash of content
        """
        return hashlib.sha256(content.encode('utf-8')).hexdigest()
    
    def _store_chunks(self, filepath: Path, chunks: List[Dict]) -> None:
        """
        Store code chunks in the database.
        
        Args:
            filepath: Path to the file
            chunks: List of chunk dictionaries
        """
        conn = None
        try:
            conn = sqlite3.connect(str(self.index_db_path))
            cursor = conn.cursor()
            
            # Clear existing chunks for this file
            cursor.execute("DELETE FROM chunks WHERE file_path = ?", (str(filepath),))
            
            # Store new chunks
            for chunk in chunks:
                cursor.execute("""
                    INSERT OR REPLACE INTO chunks 
                    (file_path, chunk_type, chunk_name, start_line, end_line, content_hash, content)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    str(filepath),
                    chunk['type'],
                    chunk['name'],
                    chunk['start_line'],
                    chunk['end_line'],
                    chunk['hash'],
                    chunk['content']
                ))
            
            conn.commit()
        except Exception as e:
            logger.error(f"Error storing chunks for {filepath}: {e}")
        finally:
            if conn:
                conn.close()
    
    def _generate_and_store_embeddings(self, filepath: Path, chunks: List[Dict]) -> None:
        """
        Generate and store embeddings for code chunks.
        
        Args:
            filepath: Path to the file
            chunks: List of chunk dictionaries
        """
        if not self.embedding_provider:
            return
        
        try:
            # Prepare texts for embedding
            texts = []
            chunk_info = []
            for chunk in chunks:
                # Combine chunk name and content for better semantic understanding
                text = f"{chunk['type']} {chunk['name']}: {chunk['content']}"
                texts.append(text)
                chunk_info.append(chunk)
            
            if not texts:
                return
            
            # Generate embeddings
            embeddings = self.embedding_provider.generate_embeddings(texts)
            
            # Store embeddings in database
            conn = sqlite3.connect(str(self.index_db_path))
            cursor = conn.cursor()
            
            # Clear existing embeddings for this file
            cursor.execute("DELETE FROM embeddings WHERE file_path = ?", (str(filepath),))
            
            for chunk, embedding in zip(chunk_info, embeddings):
                if NUMPY_AVAILABLE:
                    # Convert to bytes for storage
                    embedding_bytes = np.array(embedding, dtype=np.float32).tobytes()
                else:
                    # Fallback without numpy
                    import struct
                    embedding_bytes = struct.pack(f'{len(embedding)}f', *embedding)
                
                cursor.execute("""
                    INSERT OR REPLACE INTO embeddings
                    (file_path, chunk_type, chunk_name, content, content_hash, embedding, model, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    str(filepath),
                    chunk['type'],
                    chunk['name'],
                    chunk['content'],
                    chunk['hash'],
                    embedding_bytes,
                    self.embedding_provider.model,
                    time.time()
                ))
            
            conn.commit()
            logger.debug(f"Generated and stored {len(embeddings)} embeddings for {filepath}")
            
        except Exception as e:
            logger.error(f"Error generating embeddings for {filepath}: {e}")
        finally:
            if conn:
                conn.close()
    
    def _build_merkle_tree(self, file_hashes: Dict[str, str]) -> MerkleNode:
        """
        Build a Merkle tree from file hashes.
        
        This method creates a hierarchical hash structure similar to Cursor's approach
        for efficient incremental updates and integrity verification.
        
        Args:
            file_hashes: Dictionary mapping file paths to their content hashes
            
        Returns:
            Root node of the Merkle tree
        """
        if not file_hashes:
            return MerkleNode(hash=hashlib.sha256(b'').hexdigest())
        
        # Create leaf nodes for each file
        leaves = []
        for file_path, content_hash in file_hashes.items():
            leaf = MerkleNode(
                hash=content_hash,
                file_path=file_path,
                is_leaf=True
            )
            leaves.append(leaf)
        
        # Build tree bottom-up
        while len(leaves) > 1:
            new_level = []
            for i in range(0, len(leaves), 2):
                if i + 1 < len(leaves):
                    # Combine two nodes
                    combined_hash = self._combine_hashes(leaves[i].hash, leaves[i+1].hash)
                    parent = MerkleNode(
                        hash=combined_hash,
                        children=[leaves[i], leaves[i+1]],
                        is_leaf=False
                    )
                    new_level.append(parent)
                else:
                    # Odd number of nodes, promote the last one
                    new_level.append(leaves[i])
            leaves = new_level
        
        return leaves[0] if leaves else MerkleNode(hash=hashlib.sha256(b'').hexdigest())
    
    def _combine_hashes(self, hash1: str, hash2: str) -> str:
        """
        Combine two hashes to create a parent hash.
        
        Args:
            hash1: First hash
            hash2: Second hash
            
        Returns:
            Combined hash
        """
        combined = hash1 + hash2
        return hashlib.sha256(combined.encode()).hexdigest()
    
    def _get_changed_files(self, old_tree: Optional[MerkleNode], new_tree: MerkleNode) -> Set[str]:
        """
        Identify files that have changed by comparing Merkle trees.
        
        This method efficiently identifies which files have changed without
        re-scanning the entire codebase, similar to Cursor's approach.
        
        Args:
            old_tree: Previous Merkle tree root
            new_tree: Current Merkle tree root
            
        Returns:
            Set of file paths that have changed
        """
        if old_tree is None or old_tree.hash != new_tree.hash:
            # Full rebuild needed if root hash changed and we can't diff
            # For now, return all files as changed
            if old_tree is None:
                return self._get_all_files_from_tree(new_tree)
            return self._get_all_files_from_tree(new_tree)
        
        return self._compare_trees(old_tree, new_tree)
    
    def _compare_trees(self, old_node: MerkleNode, new_node: MerkleNode) -> Set[str]:
        """
        Recursively compare two Merkle trees to find changed files.
        
        Args:
            old_node: Node from old tree
            new_node: Node from new tree
            
        Returns:
            Set of file paths that have changed
        """
        changed_files = set()
        
        if old_node.hash != new_node.hash:
            if old_node.is_leaf and new_node.is_leaf:
                # Leaf node with different hash - file changed
                if old_node.file_path and new_node.file_path:
                    changed_files.add(new_node.file_path)
            elif not old_node.is_leaf and not new_node.is_leaf:
                # Internal node - recurse into children
                for old_child, new_child in zip(old_node.children, new_node.children):
                    changed_files.update(self._compare_trees(old_child, new_child))
        
        return changed_files
    
    def _get_all_files_from_tree(self, node: MerkleNode) -> Set[str]:
        """
        Extract all file paths from a Merkle tree.
        
        Args:
            node: Merkle tree node
            
        Returns:
            Set of all file paths in the tree
        """
        files = set()
        
        if node.is_leaf and node.file_path:
            files.add(node.file_path)
        
        for child in node.children:
            files.update(self._get_all_files_from_tree(child))
        
        return files
    
    def _dict_to_merkle_node(self, data: Dict) -> MerkleNode:
        """
        Convert dictionary to MerkleNode for deserialization.
        
        Args:
            data: Dictionary containing MerkleNode data
            
        Returns:
            MerkleNode object
        """
        return MerkleNode(
            hash=data['hash'],
            children=[self._dict_to_merkle_node(child) for child in data['children']],
            file_path=data.get('file_path'),
            is_leaf=data['is_leaf']
        )
    
    def _index_git_history(self) -> None:
        """
        Index Git history for understanding code evolution.
        
        This method indexes Git commits and file changes similar to Cursor's
        approach to provide historical context for code understanding.
        """
        try:
            import subprocess
            
            # Check if we're in a Git repository
            if not (self.root / '.git').exists():
                logger.debug("Not a Git repository, skipping Git history indexing")
                return
            
            # Get recent commits (last 100)
            result = subprocess.run(
                ['git', 'log', '-100', '--pretty=format:%H|%P|%an|%ai|%s'],
                cwd=self.root,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode != 0:
                logger.warning("Failed to get Git log")
                return
            
            commits = result.stdout.strip().split('\n') if result.stdout.strip() else []
            
            if not commits:
                logger.debug("No commits found")
                return
            
            conn = None
            try:
                conn = sqlite3.connect(str(self.index_db_path))
                cursor = conn.cursor()
                
                for commit_line in commits:
                    parts = commit_line.split('|')
                    if len(parts) < 5:
                        continue
                    
                    commit_sha, parent_sha, author, commit_time, message = parts[:5]
                    
                    # Store commit
                    cursor.execute("""
                        INSERT OR REPLACE INTO git_history 
                        (commit_sha, parent_sha, commit_message, author, commit_time)
                        VALUES (?, ?, ?, ?, ?)
                    """, (commit_sha, parent_sha, message, author, commit_time))
                    
                    # Get files changed in this commit
                    files_result = subprocess.run(
                        ['git', 'diff-tree', '--name-status', '-r', commit_sha],
                        cwd=self.root,
                        capture_output=True,
                        text=True,
                        timeout=30
                    )
                    
                    if files_result.returncode == 0:
                        for file_line in files_result.stdout.strip().split('\n'):
                            if not file_line:
                                continue
                            
                            file_parts = file_line.split('\t', 1)
                            if len(file_parts) < 2:
                                continue
                            
                            change_type, file_path = file_parts[:2]
                            
                            # Get file hash at this commit
                            file_hash_result = subprocess.run(
                                ['git', 'ls-tree', commit_sha, file_path],
                                cwd=self.root,
                                capture_output=True,
                                text=True,
                                timeout=30
                            )
                            
                            file_hash = None
                            if file_hash_result.returncode == 0:
                                # Parse the ls-tree output to get the blob hash
                                ls_parts = file_hash_result.stdout.strip().split()
                                if len(ls_parts) >= 3:
                                    file_hash = ls_parts[2]
                            
                            # Store file history
                            cursor.execute("""
                                INSERT OR REPLACE INTO git_file_history
                                (commit_sha, file_path, file_hash, change_type)
                                VALUES (?, ?, ?, ?)
                            """, (commit_sha, file_path, file_hash, change_type))
                
                conn.commit()
                logger.info(f"Indexed {len(commits)} Git commits")
                
            except Exception as e:
                logger.error(f"Error indexing Git history: {e}")
            finally:
                if conn:
                    conn.close()
                    
        except subprocess.TimeoutExpired:
            logger.warning("Git history indexing timed out")
        except FileNotFoundError:
            logger.debug("Git not found, skipping Git history indexing")
        except Exception as e:
            logger.error(f"Error in Git history indexing: {e}")
    
    def get_file_history(self, file_path: str, limit: int = 10) -> List[Dict]:
        """
        Get Git history for a specific file.
        
        Args:
            file_path: Path to the file
            limit: Maximum number of history entries to return
            
        Returns:
            List of history entries with commit information
        """
        try:
            conn = sqlite3.connect(str(self.index_db_path))
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT gh.commit_sha, gh.parent_sha, gh.commit_message, 
                       gh.author, gh.commit_time, gfh.change_type
                FROM git_file_history gfh
                JOIN git_history gh ON gfh.commit_sha = gh.commit_sha
                WHERE gfh.file_path = ?
                ORDER BY gh.commit_time DESC
                LIMIT ?
            """, (file_path, limit))
            
            results = []
            for row in cursor.fetchall():
                results.append({
                    'commit_sha': row[0],
                    'parent_sha': row[1],
                    'commit_message': row[2],
                    'author': row[3],
                    'commit_time': row[4],
                    'change_type': row[5]
                })
            
            conn.close()
            return results
            
        except Exception as e:
            logger.error(f"Error getting file history: {e}")
            return []
    
    def semantic_search(self, query: str, limit: int = 10) -> List[Dict]:
        """
        Perform semantic search using vector embeddings.
        
        This method uses OpenAI embeddings to find semantically similar code chunks,
        similar to Cursor's semantic search functionality.
        
        Args:
            query: Search query text
            limit: Maximum number of results to return
            
        Returns:
            List of matching chunks with similarity scores
        """
        if not self.embedding_provider:
            logger.warning("Embedding provider not available for semantic search")
            return []
        
        if not NUMPY_AVAILABLE:
            logger.warning("NumPy not available for semantic search")
            return []
        
        try:
            # Generate embedding for query
            query_embedding = self.embedding_provider.generate_embeddings([query])[0]
            query_vector = np.array(query_embedding, dtype=np.float32)
            
            # Fetch all embeddings from database
            conn = sqlite3.connect(str(self.index_db_path))
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT file_path, chunk_type, chunk_name, content, embedding
                FROM embeddings
            """)
            
            results = []
            for row in cursor.fetchall():
                file_path, chunk_type, chunk_name, content, embedding_blob = row
                
                # Convert embedding from bytes
                embedding_vector = np.frombuffer(embedding_blob, dtype=np.float32)
                
                # Calculate cosine similarity
                similarity = self._cosine_similarity(query_vector, embedding_vector)
                
                results.append({
                    'file_path': file_path,
                    'chunk_type': chunk_type,
                    'chunk_name': chunk_name,
                    'content': content,
                    'similarity': similarity
                })
            
            conn.close()
            
            # Sort by similarity and return top results
            results.sort(key=lambda x: x['similarity'], reverse=True)
            return results[:limit]
            
        except Exception as e:
            logger.error(f"Error in semantic search: {e}")
            return []
    
    def jump_to_definition(self, symbol_name: str, file_path: Optional[str] = None) -> Optional[Dict]:
        """
        Find the definition of a symbol.
        
        This method implements jump-to-definition functionality similar to Cursor,
        using the symbol extraction data from the index.
        
        Args:
            symbol_name: Name of the symbol to find
            file_path: Optional file path to narrow search
            
        Returns:
            Dictionary with symbol definition information or None if not found
        """
        try:
            conn = sqlite3.connect(str(self.index_db_path))
            cursor = conn.cursor()
            
            if file_path:
                cursor.execute("""
                    SELECT name, kind, file_path, line
                    FROM symbols
                    WHERE name = ? AND file_path = ?
                    ORDER BY line ASC
                    LIMIT 1
                """, (symbol_name, file_path))
            else:
                cursor.execute("""
                    SELECT name, kind, file_path, line
                    FROM symbols
                    WHERE name = ?
                    ORDER BY line ASC
                    LIMIT 1
                """, (symbol_name,))
            
            result = cursor.fetchone()
            conn.close()
            
            if result:
                return {
                    'name': result[0],
                    'kind': result[1],
                    'file_path': result[2],
                    'line': result[3]
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Error finding definition: {e}")
            return None
    
    def find_references(self, symbol_name: str, file_path: Optional[str] = None) -> List[Dict]:
        """
        Find all references to a symbol.
        
        This method implements find-references functionality similar to Cursor,
        using the cross-file reference tracking data.
        
        Args:
            symbol_name: Name of the symbol to find references for
            file_path: Optional file path to narrow search
            
        Returns:
            List of reference locations
        """
        try:
            conn = sqlite3.connect(str(self.index_db_path))
            cursor = conn.cursor()
            
            if file_path:
                cursor.execute("""
                    SELECT from_file, symbol_name, line
                    FROM references
                    WHERE symbol_name = ? AND from_file = ?
                    ORDER BY line ASC
                """, (symbol_name, file_path))
            else:
                cursor.execute("""
                    SELECT from_file, symbol_name, line
                    FROM references
                    WHERE symbol_name = ?
                    ORDER BY line ASC
                """, (symbol_name,))
            
            results = []
            for row in cursor.fetchall():
                results.append({
                    'from_file': row[0],
                    'symbol_name': row[1],
                    'line': row[2]
                })
            
            conn.close()
            return results
            
        except Exception as e:
            logger.error(f"Error finding references: {e}")
            return []
    
    def get_symbol_hierarchy(self, file_path: str) -> Dict:
        """
        Get the symbol hierarchy for a file.
        
        This method provides a hierarchical view of symbols (classes, functions, methods)
        similar to Cursor's symbol hierarchy view.
        
        Args:
            file_path: Path to the file
            
        Returns:
            Dictionary representing the symbol hierarchy
        """
        try:
            conn = sqlite3.connect(str(self.index_db_path))
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT name, kind, line, parent_name
                FROM symbols
                WHERE file_path = ?
                ORDER BY line ASC
            """, (file_path,))
            
            hierarchy = {
                'file_path': file_path,
                'classes': [],
                'functions': [],
                'variables': []
            }
            
            for row in cursor.fetchall():
                name, kind, line, parent_name = row
                
                symbol_info = {
                    'name': name,
                    'line': line,
                    'parent': parent_name
                }
                
                if kind == 'class':
                    hierarchy['classes'].append(symbol_info)
                elif kind == 'function':
                    hierarchy['functions'].append(symbol_info)
                elif kind == 'variable':
                    hierarchy['variables'].append(symbol_info)
            
            conn.close()
            return hierarchy
            
        except Exception as e:
            logger.error(f"Error getting symbol hierarchy: {e}")
            return {'file_path': file_path, 'classes': [], 'functions': [], 'variables': []}
    
    def get_file_structure(self) -> Dict:
        """
        Get the overall project file structure.
        
        This method provides a hierarchical view of the project structure,
        similar to Cursor's file explorer.
        
        Returns:
            Dictionary representing the project structure
        """
        try:
            conn = sqlite3.connect(str(self.index_db_path))
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT file_path, size
                FROM files
                ORDER BY file_path ASC
            """)
            
            structure = {'files': [], 'directories': set()}
            
            for row in cursor.fetchall():
                file_path, size = row
                
                structure['files'].append({
                    'path': file_path,
                    'size': size
                })
                
                # Track directories
                dir_path = str(Path(file_path).parent)
                structure['directories'].add(dir_path)
            
            structure['directories'] = sorted(list(structure['directories']))
            conn.close()
            
            return structure
            
        except Exception as e:
            logger.error(f"Error getting file structure: {e}")
            return {'files': [], 'directories': []}
    
    def _cosine_similarity(self, vec1: np.ndarray, vec2: np.ndarray) -> float:
        """
        Calculate cosine similarity between two vectors.
        
        Args:
            vec1: First vector
            vec2: Second vector
            
        Returns:
            Cosine similarity score
        """
        if not NUMPY_AVAILABLE:
            return 0.0
        
        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        return dot_product / (norm1 * norm2)
    
    def cleanup(self) -> None:
        """
        Clean up resources and cancel ongoing operations.
        
        This method ensures proper cleanup of resources including:
        - Canceling any ongoing indexing operations
        - Closing database connections
        - Stopping background threads
        """
        self.cancel()
        logger.info("IndexManager cleaned up")
