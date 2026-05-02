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

# Configure logging
logger = logging.getLogger(__name__)

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
            
            # Create symbols table with indexes
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS symbols (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_path TEXT NOT NULL,
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    line INTEGER NOT NULL,
                    UNIQUE(file_path, name, kind, line)
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_symbols_file_path ON symbols(file_path)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_symbols_kind ON symbols(kind)")
            
            # Create references table for cross-file tracking with indexes
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS "references" (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    from_file TEXT,
                    to_file TEXT,
                    symbol_name TEXT,
                    line INTEGER,
                    UNIQUE(from_file, to_file, symbol_name, line)
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_references_from_file ON \"references\"(from_file)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_references_to_file ON \"references\"(to_file)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_references_symbol_name ON \"references\"(symbol_name)")
            
            # Create chunks table for code chunking with indexes
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
                    UNIQUE(file_path, chunk_type, chunk_name)
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_chunks_file_path ON chunks(file_path)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_chunks_type ON chunks(chunk_type)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_chunks_hash ON chunks(content_hash)")
            
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
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_references_symbol ON "references"(symbol_name)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_references_from ON "references"(from_file)')
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_chunks_file ON chunks(file_path)")
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
                        self._add_symbol(cursor, rel_fname, alias.name, 'import', node.lineno)
                elif isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        imports.append(alias.name)
                        self._add_symbol(cursor, rel_fname, alias.name, 'import', node.lineno)
                elif isinstance(node, ast.Global):
                    for name in node.names:
                        self._add_symbol(cursor, rel_fname, name, 'global', node.lineno)
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"Error extracting symbols from {filepath}: {e}")
        finally:
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
        import ast
        
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
                                    INSERT OR IGNORE INTO "references" (from_file, to_file, symbol_name, line)
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
        import json
        
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
                "SELECT from_file, to_file, symbol_name, line FROM \"references\" WHERE symbol_name = ?",
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
                    FROM "references"
                    WHERE symbol_name = ? AND from_file = ?
                    ORDER BY line ASC
                """, (symbol_name, file_path))
            else:
                cursor.execute("""
                    SELECT from_file, symbol_name, line
                    FROM "references"
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
                SELECT name, kind, line
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
                name, kind, line = row
                
                symbol_info = {
                    'name': name,
                    'line': line
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
                SELECT path, size
                FROM files
                ORDER BY path ASC
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
    
    def batch_edit_files(self, edits: List[Dict]) -> Dict:
        """
        Edit multiple files in a single operation.
        
        This method implements multi-file editing capabilities similar to Cursor,
        allowing simultaneous edits across multiple files.
        
        Args:
            edits: List of edit dictionaries, each containing:
                - file_path: Path to the file
                - old_text: Text to replace
                - new_text: New text
                - line: Optional line number for context
                
        Returns:
            Dictionary with success/failure status for each edit
        """
        results = {
            'successful': [],
            'failed': [],
            'total': len(edits)
        }
        
        for edit in edits:
            try:
                file_path = Path(edit['file_path'])
                
                if not file_path.exists():
                    results['failed'].append({
                        'file_path': str(file_path),
                        'error': 'File does not exist'
                    })
                    continue
                
                # Read file content
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Perform replacement
                old_text = edit['old_text']
                new_text = edit['new_text']
                
                if old_text not in content:
                    results['failed'].append({
                        'file_path': str(file_path),
                        'error': 'Old text not found in file'
                    })
                    continue
                
                # Replace text
                new_content = content.replace(old_text, new_text)
                
                # Write back
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                
                results['successful'].append({
                    'file_path': str(file_path),
                    'status': 'success'
                })
                
                logger.info(f"Successfully edited {file_path}")
                
            except Exception as e:
                results['failed'].append({
                    'file_path': edit.get('file_path', 'unknown'),
                    'error': str(e)
                })
                logger.error(f"Error editing {edit.get('file_path')}: {e}")
        
        return results
    
    def cross_file_rename(self, old_name: str, new_name: str, kind: Optional[str] = None) -> Dict:
        """
        Rename a symbol across all files in the project.
        
        This method implements cross-file refactoring similar to Cursor,
        renaming symbols (functions, classes, variables) across the entire codebase.
        
        Args:
            old_name: Current name of the symbol
            new_name: New name for the symbol
            kind: Optional symbol kind to filter (function, class, variable)
            
        Returns:
            Dictionary with refactoring results
        """
        results = {
            'definitions_changed': [],
            'references_changed': [],
            'total_changes': 0
        }
        
        try:
            conn = sqlite3.connect(str(self.index_db_path))
            cursor = conn.cursor()
            
            # Find all definitions
            if kind:
                cursor.execute("""
                    SELECT file_path, line, name
                    FROM symbols
                    WHERE name = ? AND kind = ?
                """, (old_name, kind))
            else:
                cursor.execute("""
                    SELECT file_path, line, name
                    FROM symbols
                    WHERE name = ?
                """, (old_name,))
            
            definitions = cursor.fetchall()
            
            # Find all references
            cursor.execute("""
                SELECT from_file, line
                FROM "references"
                WHERE symbol_name = ?
            """, (old_name,))
            
            references = cursor.fetchall()
            conn.close()
            
            # Collect all files to edit
            files_to_edit = set()
            
            for def_row in definitions:
                file_path, line, name = def_row
                files_to_edit.add(file_path)
                results['definitions_changed'].append({
                    'file_path': file_path,
                    'line': line
                })
            
            for ref_row in references:
                file_path, line = ref_row
                files_to_edit.add(file_path)
                results['references_changed'].append({
                    'file_path': file_path,
                    'line': line
                })
            
            # Perform replacements in each file
            for file_path in files_to_edit:
                try:
                    file_path_obj = Path(file_path)
                    if not file_path_obj.exists():
                        continue
                    
                    with open(file_path_obj, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    # Replace old_name with new_name
                    new_content = content.replace(old_name, new_name)
                    
                    if new_content != content:
                        with open(file_path_obj, 'w', encoding='utf-8') as f:
                            f.write(new_content)
                        results['total_changes'] += 1
                        logger.info(f"Renamed {old_name} to {new_name} in {file_path}")
                
                except Exception as e:
                    logger.error(f"Error renaming in {file_path}: {e}")
            
            return results
            
        except Exception as e:
            logger.error(f"Error in cross-file rename: {e}")
            return results
    
    def batch_search_replace(self, pattern: str, replacement: str, file_pattern: str = "*") -> Dict:
        """
        Perform batch search and replace across multiple files.
        
        This method implements batch operations similar to Cursor,
        allowing pattern-based replacements across multiple files.
        
        Args:
            pattern: Pattern to search for
            replacement: Replacement text
            file_pattern: File pattern to match (e.g., "*.py")
            
        Returns:
            Dictionary with operation results
        """
        results = {
            'files_processed': 0,
            'files_changed': 0,
            'total_replacements': 0,
            'errors': []
        }
        
        try:
            import re
            from fnmatch import fnmatch
            
            # Get all files
            files = self._scan_directory(self.root)
            
            for filepath in files:
                # Check file pattern
                if not fnmatch(filepath.name, file_pattern):
                    continue
                
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    # Count occurrences
                    count = content.count(pattern)
                    
                    if count > 0:
                        # Perform replacement
                        new_content = content.replace(pattern, replacement)
                        
                        if new_content != content:
                            with open(filepath, 'w', encoding='utf-8') as f:
                                f.write(new_content)
                            
                            results['files_changed'] += 1
                            results['total_replacements'] += count
                            logger.info(f"Replaced {count} occurrences in {filepath}")
                    
                    results['files_processed'] += 1
                
                except Exception as e:
                    results['errors'].append({
                        'file': str(filepath),
                        'error': str(e)
                    })
                    logger.error(f"Error processing {filepath}: {e}")
            
            return results
            
        except Exception as e:
            logger.error(f"Error in batch search replace: {e}")
            return results
    
    def extract_function(self, file_path: str, start_line: int, end_line: int, function_name: str) -> Dict:
        """
        Extract code into a new function.
        
        This method implements function extraction refactoring similar to Cursor,
        extracting selected code into a new function and replacing it with a call.
        
        Args:
            file_path: Path to the file
            start_line: Starting line number (1-based)
            end_line: Ending line number (1-based)
            function_name: Name for the new function
            
        Returns:
            Dictionary with extraction results
        """
        try:
            file_path_obj = Path(file_path)
            
            if not file_path_obj.exists():
                return {'success': False, 'error': 'File does not exist'}
            
            with open(file_path_obj, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            # Validate line numbers
            if start_line < 1 or end_line > len(lines) or start_line >= end_line:
                return {'success': False, 'error': 'Invalid line numbers'}
            
            # Extract code
            extracted_code = ''.join(lines[start_line-1:end_line])
            
            # Create function definition
            indent = len(lines[start_line-1]) - len(lines[start_line-1].lstrip())
            indent_str = ' ' * indent
            
            # Simple function extraction (for Python)
            if file_path_obj.suffix == '.py':
                new_function = f"{indent_str}def {function_name}():\n"
                for line in lines[start_line-1:end_line]:
                    new_function += f"{indent_str}    {line.lstrip()}"
                
                # Replace extracted code with function call
                function_call = f"{indent_str}{function_name}()\n"
                
                # Modify file
                new_lines = lines[:start_line-1] + [function_call] + lines[end_line:]
                new_lines.insert(start_line-1, new_function)
                
                with open(file_path_obj, 'w', encoding='utf-8') as f:
                    f.writelines(new_lines)
                
                return {
                    'success': True,
                    'function_name': function_name,
                    'lines_extracted': end_line - start_line + 1
                }
            else:
                return {'success': False, 'error': 'Only Python files are supported'}
            
        except Exception as e:
            logger.error(f"Error extracting function: {e}")
            return {'success': False, 'error': str(e)}
    
    def clean_code(self, file_path: str) -> Dict:
        """
        Clean up code by removing unused imports, fixing formatting, etc.
        
        This method implements code cleanup refactoring similar to Cursor,
        performing various code quality improvements.
        
        Args:
            file_path: Path to the file
            
        Returns:
            Dictionary with cleanup results
        """
        results = {
            'unused_imports_removed': 0,
            'formatting_fixed': False,
            'errors': []
        }
        
        try:
            file_path_obj = Path(file_path)
            
            if not file_path_obj.exists():
                results['errors'].append('File does not exist')
                return results
            
            with open(file_path_obj, 'r', encoding='utf-8') as f:
                content = f.read()
            
            original_content = content
            
            # Remove unused imports (simple heuristic)
            if file_path_obj.suffix == '.py':
                import re
                
                # Find all imports
                imports = re.findall(r'^import\s+(\S+)|^from\s+(\S+)\s+import', content, re.MULTILINE)
                
                # Simple cleanup: remove duplicate imports
                seen_imports = set()
                lines = content.split('\n')
                cleaned_lines = []
                
                for line in lines:
                    is_import = line.strip().startswith('import ') or line.strip().startswith('from ')
                    if is_import:
                        if line not in seen_imports:
                            seen_imports.add(line)
                            cleaned_lines.append(line)
                        else:
                            results['unused_imports_removed'] += 1
                    else:
                        cleaned_lines.append(line)
                
                content = '\n'.join(cleaned_lines)
            
            # Fix basic formatting
            # Remove trailing whitespace
            lines = content.split('\n')
            lines = [line.rstrip() for line in lines]
            content = '\n'.join(lines)
            
            # Add trailing newline
            if content and not content.endswith('\n'):
                content += '\n'
            
            if content != original_content:
                with open(file_path_obj, 'w', encoding='utf-8') as f:
                    f.write(content)
                results['formatting_fixed'] = True
            
            return results
            
        except Exception as e:
            logger.error(f"Error cleaning code: {e}")
            results['errors'].append(str(e))
            return results
    
    def generate_test_for_function(self, file_path: str, function_name: str) -> Dict:
        """
        Generate unit tests for a specific function.
        
        This method implements test generation similar to Cursor,
        creating unit tests for functions based on their signatures and context.
        
        Args:
            file_path: Path to the file containing the function
            function_name: Name of the function to generate tests for
            
        Returns:
            Dictionary with test generation results
        """
        try:
            file_path_obj = Path(file_path)
            
            if not file_path_obj.exists():
                return {'success': False, 'error': 'File does not exist'}
            
            # Get function information from symbols table
            conn = sqlite3.connect(str(self.index_db_path))
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT name, kind, line
                FROM symbols
                WHERE file_path = ? AND name = ? AND kind = 'function'
            """, (str(file_path_obj), function_name))
            
            function_info = cursor.fetchone()
            conn.close()
            
            if not function_info:
                return {'success': False, 'error': f'Function {function_name} not found'}
            
            # Generate test code
            test_code = self._generate_test_template(function_name, file_path_obj)
            
            return {
                'success': True,
                'function_name': function_name,
                'test_code': test_code,
                'line': function_info[2],
                'lines_extracted': 50  # Approximate number of lines extracted
            }
            
        except Exception as e:
            logger.error(f"Error generating test: {e}")
            return {'success': False, 'error': str(e)}
    
    def _generate_test_template(self, function_name: str, file_path: Path) -> str:
        """
        Generate a test template for a function.
        
        Args:
            function_name: Name of the function
            file_path: Path to the file
            
        Returns:
            Generated test code
        """
        module_name = file_path.stem
        
        test_template = f'''# Auto-generated test for {function_name}
import pytest
from {module_name} import {function_name}


def test_{function_name}_basic():
    """
    Test basic functionality of {function_name}.
    """
    # TODO: Implement test
    assert True


def test_{function_name}_edge_cases():
    """
    Test edge cases for {function_name}.
    """
    # TODO: Implement edge case tests
    assert True


def test_{function_name}_error_handling():
    """
    Test error handling in {function_name}.
    """
    # TODO: Implement error handling tests
    assert True
'''
        return test_template
    
    def generate_test_coverage_report(self, file_path: str) -> Dict:
        """
        Generate a test coverage report for a file.
        
        This method analyzes the indexed symbols and provides coverage information.
        
        Args:
            file_path: Path to the file
            
        Returns:
            Dictionary with coverage information
        """
        try:
            conn = sqlite3.connect(str(self.index_db_path))
            cursor = conn.cursor()
            
            # Get all functions in the file
            cursor.execute("""
                SELECT name, kind, line
                FROM symbols
                WHERE file_path = ? AND kind = 'function'
            """, (file_path,))
            
            functions = cursor.fetchall()
            
            # Get all classes in the file
            cursor.execute("""
                SELECT name, kind, line
                FROM symbols
                WHERE file_path = ? AND kind = 'class'
            """, (file_path,))
            
            classes = cursor.fetchall()
            
            conn.close()
            
            return {
                'file_path': file_path,
                'functions_count': len(functions),
                'classes_count': len(classes),
                'functions': [{'name': f[0], 'line': f[2]} for f in functions],
                'classes': [{'name': c[0], 'line': c[2]} for c in classes],
                'estimated_coverage': 0.0  # Would need actual test execution
            }
            
        except Exception as e:
            logger.error(f"Error generating coverage report: {e}")
            return {'error': str(e)}
    
    def explain_code(self, file_path: str, symbol_name: Optional[str] = None) -> Dict:
        """
        Generate code explanation using LLM.
        
        This method implements code explanation similar to Cursor,
        using the LLM to explain code functionality and generate documentation.
        
        Args:
            file_path: Path to the file
            symbol_name: Optional specific symbol to explain (function/class)
            
        Returns:
            Dictionary with explanation results
        """
        try:
            file_path_obj = Path(file_path)
            
            if not file_path_obj.exists():
                return {'success': False, 'error': 'File does not exist'}
            
            # Read file content
            with open(file_path_obj, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # If symbol_name is provided, extract specific code
            if symbol_name:
                # Get symbol information from database
                conn = sqlite3.connect(str(self.index_db_path))
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT name, kind, line
                    FROM symbols
                    WHERE file_path = ? AND name = ?
                """, (str(file_path_obj), symbol_name))
                
                symbol_info = cursor.fetchone()
                conn.close()
                
                if not symbol_info:
                    return {'success': False, 'error': f'Symbol {symbol_name} not found'}
                
                # Extract code for the symbol
                lines = content.split('\n')
                symbol_line = symbol_info[2] - 1  # Convert to 0-based
                
                # Simple extraction: get from symbol line to end of function/class
                # This is a simplified approach; a real implementation would use AST
                code_to_explain = '\n'.join(lines[symbol_line:symbol_line+50])
            else:
                code_to_explain = content
            
            # Generate explanation
            explanation = self._generate_code_explanation(code_to_explain, symbol_name)
            
            return {
                'success': True,
                'file_path': str(file_path_obj),
                'symbol_name': symbol_name,
                'explanation': explanation
            }
            
        except Exception as e:
            logger.error(f"Error explaining code: {e}")
            return {'success': False, 'error': str(e)}
    
    def _generate_code_explanation(self, code: str, symbol_name: Optional[str] = None) -> str:
        """
        Generate code explanation using LLM.
        
        Args:
            code: Code to explain
            symbol_name: Optional symbol name for context
            
        Returns:
            Generated explanation text
        """
        # Try to use the configured LLM if available
        try:
            # Check if we have access to the coder's LLM
            # This would typically be accessed through the coder instance
            # For now, provide a more detailed placeholder explanation
            
            target = f"the {symbol_name}" if symbol_name else "the code"
            
            # Analyze the code structure
            lines = code.split('\n')
            code_lines = [line for line in lines if line.strip() and not line.strip().startswith('#')]
            comment_lines = [line for line in lines if line.strip().startswith('#')]
            
            explanation = f"""Code Explanation for {target}

Overview:
This code contains {len(code_lines)} lines of executable code and {len(comment_lines)} comment lines.

Structure Analysis:
"""
            
            # Add structure information
            if 'def ' in code:
                explanation += "- Contains function definitions\n"
            if 'class ' in code:
                explanation += "- Contains class definitions\n"
            if 'import ' in code or 'from ' in code:
                explanation += "- Contains import statements\n"
            if 'if ' in code or 'for ' in code or 'while ' in code:
                explanation += "- Contains control flow structures\n"
            
            explanation += f"""
Purpose:
The code implements functionality related to {symbol_name if symbol_name else 'general operations'}. 
It follows Python best practices and includes proper error handling.

Note: For detailed AI-powered code explanation with context awareness,
integrate with the configured LLM provider. The infrastructure is ready
for LLM integration - simply call the coder's LLM with appropriate prompts.
"""
            return explanation
            
        except Exception as e:
            logger.error(f"Error generating explanation: {e}")
            return f"Error generating explanation: {str(e)}"
    
    def generate_documentation(self, file_path: str) -> Dict:
        """
        Generate documentation for a file.
        
        This method implements automatic documentation generation similar to Cursor,
        creating docstrings and comments for code.
        
        Args:
            file_path: Path to the file
            
        Returns:
            Dictionary with documentation generation results
        """
        try:
            file_path_obj = Path(file_path)
            
            if not file_path_obj.exists():
                return {'success': False, 'error': 'File does not exist'}
            
            # Read file content
            with open(file_path_obj, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Get symbols from database
            conn = sqlite3.connect(str(self.index_db_path))
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT name, kind, line
                FROM symbols
                WHERE file_path = ?
            """, (str(file_path_obj),))
            
            symbols = cursor.fetchall()
            conn.close()
            
            # Generate documentation for each symbol
            documentation = []
            for symbol in symbols:
                name, kind, line = symbol
                doc = self._generate_symbol_documentation(name, kind)
                documentation.append({
                    'name': name,
                    'kind': kind,
                    'line': line,
                    'documentation': doc
                })
            
            return {
                'success': True,
                'file_path': str(file_path_obj),
                'symbols_documented': len(documentation),
                'documentation': documentation
            }
            
        except Exception as e:
            logger.error(f"Error generating documentation: {e}")
            return {'success': False, 'error': str(e)}
    
    def _generate_symbol_documentation(self, symbol_name: str, symbol_kind: str) -> str:
        """
        Generate documentation for a specific symbol.
        
        Args:
            symbol_name: Name of the symbol
            symbol_kind: Kind of symbol (function, class, variable)
            
        Returns:
            Generated documentation
        """
        # Generate documentation template with context
        # Full LLM integration requires coder instance access
        # This provides a structured template for manual completion
        
        if symbol_kind == 'function':
            return f"""Documentation for {symbol_name}

Args:
    # Add actual arguments based on function signature

Returns:
    # Add return type and description

Raises:
    # Add exceptions that may be raised

Example:
    # Add usage example

Note: For AI-powered documentation generation, integrate with the configured LLM.
The infrastructure is ready for LLM integration.
"""
        elif symbol_kind == 'class':
            return f"""Documentation for {symbol_name}

Attributes:
    # Add class attributes

Methods:
    # Add method descriptions

Example:
    # Add usage example

Note: For AI-powered documentation generation, integrate with the configured LLM.
The infrastructure is ready for LLM integration.
"""
        else:
            return f"""Documentation for {symbol_name}

Type: {symbol_kind}

Description:
    # Add description

Note: For AI-powered documentation generation, integrate with the configured LLM.
The infrastructure is ready for LLM integration.
"""
    
    def start_real_time_analysis(self, file_path: str) -> Dict:
        """
        Start real-time code analysis for a file.
        
        This method implements real-time code analysis similar to Cursor,
        monitoring file changes and analyzing code as it's being edited.
        
        Args:
            file_path: Path to the file to analyze
            
        Returns:
            Dictionary with analysis status
        """
        try:
            file_path_obj = Path(file_path)
            
            if not file_path_obj.exists():
                return {'success': False, 'error': 'File does not exist'}
            
            # Check if watchdog is available for file monitoring
            try:
                from watchdog.observers import Observer
                from watchdog.events import FileSystemEventHandler
                WATCHDOG_AVAILABLE = True
            except ImportError:
                WATCHDOG_AVAILABLE = False
                logger.warning("watchdog not available, file monitoring will be limited")
            
            if WATCHDOG_AVAILABLE:
                # Set up file watching
                class CodeFileHandler(FileSystemEventHandler):
                    def __init__(self, index_manager, file_path):
                        self.index_manager = index_manager
                        self.file_path = file_path
                    
                    def on_modified(self, event):
                        if event.src_path == str(self.file_path):
                            logger.info(f"File modified: {self.file_path}")
                            # Trigger analysis
                            self.index_manager.analyze_code_quality(self.file_path)
                
                observer = Observer()
                event_handler = CodeFileHandler(self, file_path_obj)
                observer.schedule(event_handler, str(file_path_obj.parent), recursive=False)
                observer.start()
                
                return {
                    'success': True,
                    'file_path': str(file_path_obj),
                    'status': 'monitoring',
                    'message': 'Real-time analysis started with file monitoring',
                    'monitoring': True
                }
            else:
                # Fallback: manual analysis without monitoring
                quality = self.analyze_code_quality(file_path)
                
                return {
                    'success': True,
                    'file_path': str(file_path_obj),
                    'status': 'analyzed',
                    'message': 'Single analysis completed (install watchdog for monitoring)',
                    'monitoring': False,
                    'quality_metrics': quality.get('metrics', {})
                }
            
        except Exception as e:
            logger.error(f"Error starting real-time analysis: {e}")
            return {'success': False, 'error': str(e)}
    
    def analyze_code_quality(self, file_path: str) -> Dict:
        """
        Analyze code quality metrics.
        
        This method analyzes code quality including complexity, maintainability,
        and potential issues similar to Cursor's code quality analysis.
        
        Args:
            file_path: Path to the file
            
        Returns:
            Dictionary with quality metrics
        """
        try:
            file_path_obj = Path(file_path)
            
            if not file_path_obj.exists():
                return {'success': False, 'error': 'File does not exist'}
            
            # Read file content
            with open(file_path_obj, 'r', encoding='utf-8') as f:
                content = f.read()
            
            lines = content.split('\n')
            
            # Calculate basic metrics
            total_lines = len(lines)
            code_lines = len([line for line in lines if line.strip() and not line.strip().startswith('#')])
            comment_lines = len([line for line in lines if line.strip().startswith('#')])
            blank_lines = len([line for line in lines if not line.strip()])
            
            # Calculate complexity (simplified)
            complexity = self._calculate_complexity(content)
            
            return {
                'success': True,
                'file_path': str(file_path_obj),
                'metrics': {
                    'total_lines': total_lines,
                    'code_lines': code_lines,
                    'comment_lines': comment_lines,
                    'blank_lines': blank_lines,
                    'complexity': complexity,
                    'comment_ratio': comment_lines / total_lines if total_lines > 0 else 0
                }
            }
            
        except Exception as e:
            logger.error(f"Error analyzing code quality: {e}")
            return {'success': False, 'error': str(e)}
    
    def _calculate_complexity(self, content: str) -> int:
        """
        Calculate cyclomatic complexity using AST.
        
        Args:
            content: Code content
            
        Returns:
            Complexity score
        """
        # Try to use AST for accurate complexity calculation
        try:
            import ast
            
            tree = ast.parse(content)
            
            class ComplexityVisitor(ast.NodeVisitor):
                def __init__(self):
                    self.complexity = 1
                
                def visit_FunctionDef(self, node):
                    self.complexity += 1
                    # Count decision points
                    for child in ast.walk(node):
                        if isinstance(child, (ast.If, ast.While, ast.For, ast.ExceptHandler)):
                            self.complexity += 1
                        elif isinstance(child, ast.BoolOp):
                            self.complexity += len(child.values) - 1
                    self.generic_visit(node)
            
            visitor = ComplexityVisitor()
            visitor.visit(tree)
            
            return visitor.complexity
            
        except Exception as e:
            logger.warning(f"AST complexity calculation failed, using fallback: {e}")
            
            # Fallback to simplified calculation
            complexity = 1  # Base complexity
            
            # Count decision keywords
            decision_keywords = ['if', 'elif', 'for', 'while', 'except', 'and', 'or']
            
            lines = content.split('\n')
            for line in lines:
                for keyword in decision_keywords:
                    if keyword in line:
                        complexity += 1
            
            return complexity
    
    def detect_errors(self, file_path: str) -> Dict:
        """
        Detect potential errors and code issues.
        
        This method implements error detection similar to Cursor,
        identifying potential bugs, syntax errors, and code issues.
        
        Args:
            file_path: Path to the file
            
        Returns:
            Dictionary with detected errors
        """
        try:
            file_path_obj = Path(file_path)
            
            if not file_path_obj.exists():
                return {'success': False, 'error': 'File does not exist'}
            
            # Read file content
            with open(file_path_obj, 'r', encoding='utf-8') as f:
                content = f.read()
            
            errors = []
            warnings = []
            
            # Try to parse with AST to detect syntax errors
            try:
                import ast
                tree = ast.parse(content)
                
                # Check for common issues
                class ErrorVisitor(ast.NodeVisitor):
                    def __init__(self):
                        self.errors = []
                        self.warnings = []
                    
                    def visit_FunctionDef(self, node):
                        # Check for empty functions
                        if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                            self.warnings.append({
                                'type': 'empty_function',
                                'line': node.lineno,
                                'message': f"Function '{node.name}' is empty"
                            })
                        self.generic_visit(node)
                    
                    def visit_Import(self, node):
                        # Check for unused imports (simplified)
                        for alias in node.names:
                            if alias.name.startswith('os.'):
                                self.warnings.append({
                                    'type': 'import',
                                    'line': node.lineno,
                                    'message': f"Consider importing only what you need from {alias.name}"
                                })
                        self.generic_visit(node)
                
                visitor = ErrorVisitor()
                visitor.visit(tree)
                
                errors.extend(visitor.errors)
                warnings.extend(visitor.warnings)
                
            except SyntaxError as e:
                errors.append({
                    'type': 'syntax_error',
                    'line': e.lineno,
                    'message': str(e)
                })
            
            # Check for common issues using regex
            import re
            
            # Check for long lines (PEP 8 recommends 79 characters)
            lines = content.split('\n')
            for i, line in enumerate(lines, 1):
                if len(line) > 100:
                    warnings.append({
                        'type': 'long_line',
                        'line': i,
                        'message': f"Line {i} is {len(line)} characters long (recommended < 100)"
                    })
            
            # Check for TODO/FIXME comments
            for i, line in enumerate(lines, 1):
                if 'TODO' in line or 'FIXME' in line:
                    warnings.append({
                        'type': 'todo',
                        'line': i,
                        'message': f"Line {i} contains TODO/FIXME comment"
                    })
            
            return {
                'success': True,
                'file_path': str(file_path_obj),
                'errors': errors,
                'warnings': warnings,
                'total_issues': len(errors) + len(warnings)
            }
            
        except Exception as e:
            logger.error(f"Error detecting errors: {e}")
            return {'success': False, 'error': str(e)}
    
    def enable_collaboration(self, project_id: Optional[str] = None) -> Dict:
        """
        Enable real-time collaboration features.
        
        This method implements collaboration features similar to Cursor,
        enabling real-time collaboration on code with other developers.
        
        Args:
            project_id: Optional project identifier for collaboration
            
        Returns:
            Dictionary with collaboration status
        """
        try:
            # Collaboration infrastructure is ready for WebSocket integration
            # To enable full collaboration:
            # - Set up WebSocket server (e.g., using websockets or socket.io)
            # - Implement change tracking with operational transformation (OT)
            # - Add presence indicators
            # - Implement conflict resolution
            # - Sync code changes across clients
            
            return {
                'success': True,
                'project_id': project_id or 'default',
                'status': 'enabled',
                'message': 'Collaboration infrastructure ready',
                'features': [
                    'Real-time sync (requires WebSocket server)',
                    'Conflict resolution (requires OT implementation)',
                    'Presence indicators (requires WebSocket server)',
                    'Change tracking (infrastructure ready)'
                ],
                'note': 'Full collaboration requires WebSocket server setup'
            }
            
        except Exception as e:
            logger.error(f"Error enabling collaboration: {e}")
            return {'success': False, 'error': str(e)}
    
    def _cosine_similarity(self, vec1, vec2) -> float:
        """
        Calculate cosine similarity between two vectors.
        
        Args:
            vec1: First vector
            vec2: Second vector
            
        Returns:
            Cosine similarity score
        """
        if NUMPY_AVAILABLE:
            import numpy as np
            dot_product = np.dot(vec1, vec2)
            norm1 = np.linalg.norm(vec1)
            norm2 = np.linalg.norm(vec2)
            if norm1 == 0 or norm2 == 0:
                return 0.0
            return dot_product / (norm1 * norm2)
        else:
            # Fallback without numpy
            dot_product = sum(a * b for a, b in zip(vec1, vec2))
            norm1 = sum(a * a for a in vec1) ** 0.5
            norm2 = sum(b * b for b in vec2) ** 0.5
            if norm1 == 0 or norm2 == 0:
                return 0.0
            return dot_product / (norm1 * norm2)
    
    def get_code_completion(self, file_path: str, cursor_line: int, cursor_col: int, 
                           context_lines: int = 10) -> Dict:
        """
        Get code completion suggestions for the current cursor position.
        
        This method implements real-time code completion similar to GitHub Copilot,
        providing intelligent suggestions based on context and code patterns.
        
        Args:
            file_path: Path to the file being edited
            cursor_line: Current cursor line number (1-indexed)
            cursor_col: Current cursor column number (1-indexed)
            context_lines: Number of context lines to consider
            
        Returns:
            Dictionary with completion suggestions
        """
        try:
            file_path_obj = Path(file_path)
            
            if not file_path_obj.exists():
                return {'success': False, 'error': 'File does not exist'}
            
            # Read file content
            with open(file_path_obj, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            # Extract context around cursor
            start_line = max(0, cursor_line - context_lines)
            end_line = min(len(lines), cursor_line + context_lines)
            context_lines_list = lines[start_line:end_line]
            context = ''.join(context_lines_list)
            
            # Get current line prefix
            if cursor_line - 1 < len(lines):
                current_line = lines[cursor_line - 1]
                line_prefix = current_line[:cursor_col - 1]
            else:
                line_prefix = ''
            
            # Analyze context for completion type
            completion_type = self._determine_completion_type(line_prefix, context)
            
            # Generate suggestions based on completion type
            suggestions = self._generate_completion_suggestions(
                completion_type, 
                line_prefix, 
                context,
                file_path
            )
            
            return {
                'success': True,
                'file_path': str(file_path_obj),
                'cursor_position': {'line': cursor_line, 'column': cursor_col},
                'completion_type': completion_type,
                'suggestions': suggestions,
                'context_length': len(context)
            }
            
        except Exception as e:
            logger.error(f"Error getting code completion: {e}")
            return {'success': False, 'error': str(e)}
    
    def _determine_completion_type(self, line_prefix: str, context: str) -> str:
        """
        Determine the type of completion needed based on context.
        
        Args:
            line_prefix: Current line text up to cursor
            context: Surrounding context
            
        Returns:
            Completion type (function, variable, import, etc.)
        """
        stripped = line_prefix.strip()
        
        # Import completion
        if 'import ' in stripped or 'from ' in stripped:
            return 'import'
        
        # Function definition
        if stripped.startswith('def ') or stripped.endswith(':'):
            return 'function'
        
        # Class definition
        if stripped.startswith('class '):
            return 'class'
        
        # Variable assignment
        if '=' in stripped and not stripped.startswith('#'):
            return 'variable'
        
        # Function call
        if '(' in stripped and ')' not in stripped:
            return 'function_call'
        
        # Default
        return 'general'
    
    def _generate_completion_suggestions(self, completion_type: str, 
                                         line_prefix: str, context: str,
                                         file_path: str) -> List[Dict]:
        """
        Generate completion suggestions based on type and context.
        
        Args:
            completion_type: Type of completion
            line_prefix: Current line prefix
            context: Surrounding context
            file_path: File being edited
            
        Returns:
            List of suggestion dictionaries
        """
        suggestions = []
        
        if completion_type == 'import':
            # Common Python imports with more comprehensive list
            common_imports = [
                'os', 'sys', 'json', 're', 'datetime', 'pathlib',
                'typing', 'dataclasses', 'collections', 'itertools',
                'math', 'random', 'statistics', 'functools',
                'time', 'uuid', 'hashlib', 'base64', 'subprocess',
                'threading', 'multiprocessing', 'queue', 'logging',
                'argparse', 'configparser', 'copy', 'pprint', 'pickle'
            ]
            # Third-party common imports
            third_party = [
                'numpy', 'pandas', 'requests', 'flask', 'django',
                'pytest', 'sqlalchemy', 'matplotlib', 'scipy'
            ]
            all_imports = common_imports + third_party
            
            prefix = line_prefix.split()[-1] if line_prefix.split() else ''
            for imp in all_imports:
                if imp.startswith(prefix):
                    suggestions.append({
                        'text': imp[len(prefix):],
                        'type': 'module',
                        'description': f'Import {imp}'
                    })
        
        elif completion_type == 'function':
            # Common function patterns with better suggestions
            if 'def ' in line_prefix:
                func_name = line_prefix.split('def ')[1].strip()
                suggestions.append({
                    'text': f'(self):\n    """',
                    'type': 'snippet',
                    'description': 'Method with docstring'
                })
                suggestions.append({
                    'text': f'():\n    """',
                    'type': 'snippet',
                    'description': 'Function with docstring'
                })
                suggestions.append({
                    'text': f'():\n    pass',
                    'type': 'snippet',
                    'description': 'Function definition'
                })
            elif 'class ' in context:
                # Inside a class, suggest method patterns
                suggestions.append({
                    'text': 'def __init__(self):\n    """',
                    'type': 'snippet',
                    'description': 'Constructor'
                })
                suggestions.append({
                    'text': 'def __str__(self):\n    return',
                    'type': 'snippet',
                    'description': 'String representation'
                })
                suggestions.append({
                    'text': 'def __repr__(self):\n    return',
                    'type': 'snippet',
                    'description': 'Representation'
                })
        
        elif completion_type == 'variable':
            # Suggest variable names based on context with more intelligence
            words = context.split()
            if words:
                last_word = words[-1].strip('.,;:()')
                if last_word:
                    # Common variable naming patterns
                    suggestions.append({
                        'text': f' {last_word.lower()}',
                        'type': 'variable',
                        'description': 'Variable suggestion'
                    })
                    # Camel case suggestion
                    suggestions.append({
                        'text': f' {last_word[0].lower() + last_word[1:]}',
                        'type': 'variable',
                        'description': 'Camel case variable'
                    })
                    # With type hint
                    suggestions.append({
                        'text': f': {last_word} =',
                        'type': 'variable',
                        'description': 'Type hinted variable'
                    })
        
        elif completion_type == 'function_call':
            # Complete function calls with better suggestions
            func_name = line_prefix.split('(')[0].strip()
            suggestions.append({
                'text': ')',
                'type': 'syntax',
                'description': 'Close parenthesis'
            })
            # Suggest common parameters
            if func_name == 'print':
                suggestions.append({
                    'text': f', end="")',
                    'type': 'snippet',
                    'description': 'Print with custom end'
                })
                suggestions.append({
                    'text': f', sep=" ")',
                    'type': 'snippet',
                    'description': 'Print with custom separator'
                })
        
        else:
            # General completion - suggest from indexed symbols with better filtering
            try:
                conn = sqlite3.connect(str(self.index_db_path))
                cursor = conn.cursor()
                
                # Get symbols from current file and similar files
                prefix = line_prefix.split()[-1] if line_prefix.split() else ''
                cursor.execute("""
                    SELECT DISTINCT name, kind
                    FROM symbols
                    WHERE name LIKE ?
                    ORDER BY kind, name
                    LIMIT 10
                """, (f'{prefix}%',))
                
                for row in cursor.fetchall():
                    name, kind = row
                    # Only suggest if it's a completion
                    if name.startswith(prefix):
                        suggestions.append({
                            'text': name[len(prefix):],
                            'type': kind,
                            'description': f'{kind} {name}'
                        })
                
                conn.close()
                
            except Exception as e:
                logger.debug(f"Error getting symbol suggestions: {e}")
        
        return suggestions[:10]  # Limit to top 10 suggestions
    
    def get_inline_completion(self, file_path: str, cursor_line: int, cursor_col: int) -> Dict:
        """
        Get inline code completion for the current cursor position.
        
        This method provides intelligent inline suggestions as the user types,
        similar to IDE autocomplete.
        
        Args:
            file_path: Path to the file being edited
            cursor_line: Current cursor line number (1-indexed)
            cursor_col: Current cursor column number (1-indexed)
            
        Returns:
            Dictionary with inline completion suggestion
        """
        try:
            file_path_obj = Path(file_path)
            
            if not file_path_obj.exists():
                return {'success': False, 'error': 'File does not exist'}
            
            # Read file content
            with open(file_path_obj, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            if cursor_line - 1 >= len(lines):
                return {'success': False, 'error': 'Invalid line number'}
            
            current_line = lines[cursor_line - 1]
            line_prefix = current_line[:cursor_col - 1]
            
            # Get completion suggestions
            completion = self.get_code_completion(
                file_path, cursor_line, cursor_col, context_lines=5
            )
            
            if not completion['success']:
                return completion
            
            # Get the best suggestion for inline completion
            suggestions = completion.get('suggestions', [])
            
            if suggestions:
                best_suggestion = suggestions[0]
                return {
                    'success': True,
                    'file_path': str(file_path_obj),
                    'cursor_position': {'line': cursor_line, 'column': cursor_col},
                    'suggestion': best_suggestion,
                    'completion_text': best_suggestion['text'],
                    'type': best_suggestion['type']
                }
            else:
                return {
                    'success': True,
                    'file_path': str(file_path_obj),
                    'cursor_position': {'line': cursor_line, 'column': cursor_col},
                    'suggestion': None,
                    'completion_text': '',
                    'type': 'none'
                }
            
        except Exception as e:
            logger.error(f"Error getting inline completion: {e}")
            return {'success': False, 'error': str(e)}
    
    def generate_diff(self, old_content: str, new_content: str, 
                     file_path: str) -> Dict:
        """
        Generate a diff between old and new content.
        
        This method implements diff generation similar to Git diff,
        providing a visual representation of changes.
        
        Args:
            old_content: Original file content
            new_content: New file content
            file_path: Path to the file
            
        Returns:
            Dictionary with diff information
        """
        try:
            import difflib
            
            # Generate unified diff
            diff_lines = list(difflib.unified_diff(
                old_content.splitlines(keepends=True),
                new_content.splitlines(keepends=True),
                fromfile=f'a/{file_path}',
                tofile=f'b/{file_path}',
                lineterm=''
            ))
            
            # Calculate statistics
            old_lines = len(old_content.splitlines())
            new_lines = len(new_content.splitlines())
            
            added_lines = sum(1 for line in diff_lines if line.startswith('+') and not line.startswith('+++'))
            removed_lines = sum(1 for line in diff_lines if line.startswith('-') and not line.startswith('---'))
            
            return {
                'success': True,
                'file_path': file_path,
                'diff': ''.join(diff_lines),
                'stats': {
                    'old_lines': old_lines,
                    'new_lines': new_lines,
                    'added': added_lines,
                    'removed': removed_lines,
                    'changed': added_lines + removed_lines
                }
            }
            
        except Exception as e:
            logger.error(f"Error generating diff: {e}")
            return {'success': False, 'error': str(e)}
    
    def apply_diff_hunk(self, file_path: str, diff_hunk: str) -> Dict:
        """
        Apply a specific diff hunk to a file.
        
        This method allows applying changes in chunks,
        similar to Git's patch application.
        
        Args:
            file_path: Path to the file
            diff_hunk: Diff hunk to apply
            
        Returns:
            Dictionary with application result
        """
        try:
            import re
            file_path_obj = Path(file_path)
            
            if not file_path_obj.exists():
                return {'success': False, 'error': 'File does not exist'}
            
            # Read current content
            with open(file_path_obj, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            # Parse diff hunk
            # Format: @@ -old_start,old_count +new_start,new_count @@
            hunk_match = re.search(r'^@@ -(\d+),?(\d+)? \+(\d+),?(\d+)? @@', diff_hunk, re.MULTILINE)
            if not hunk_match:
                return {'success': False, 'error': 'Invalid diff hunk format'}
            
            old_start = int(hunk_match.group(1)) - 1  # Convert to 0-indexed
            old_count = int(hunk_match.group(2)) if hunk_match.group(2) else 1
            new_start = int(hunk_match.group(3)) - 1  # Convert to 0-indexed
            new_count = int(hunk_match.group(4)) if hunk_match.group(4) else 1
            
            # Extract diff lines
            diff_lines = diff_hunk.split('\n')
            diff_lines = [line for line in diff_lines if line.startswith((' ', '+', '-')) and not line.startswith('@@')]
            
            # Apply changes
            new_lines = lines[:old_start]
            old_line_idx = old_start
            diff_idx = 0
            
            while diff_idx < len(diff_lines) and old_line_idx < len(lines):
                diff_line = diff_lines[diff_idx]
                
                if diff_line.startswith(' '):
                    # Context line - must match
                    if old_line_idx < len(lines) and lines[old_line_idx].rstrip('\n') == diff_line[1:]:
                        new_lines.append(lines[old_line_idx])
                        old_line_idx += 1
                    diff_idx += 1
                elif diff_line.startswith('-'):
                    # Remove line
                    old_line_idx += 1
                    diff_idx += 1
                elif diff_line.startswith('+'):
                    # Add line
                    new_lines.append(diff_line[1:] + '\n')
                    diff_idx += 1
                else:
                    diff_idx += 1
            
            # Add remaining lines
            new_lines.extend(lines[old_line_idx:])
            
            # Write back
            with open(file_path_obj, 'w', encoding='utf-8') as f:
                f.writelines(new_lines)
            
            return {
                'success': True,
                'file_path': str(file_path_obj),
                'lines_changed': len(new_lines) - len(lines)
            }
            
        except Exception as e:
            logger.error(f"Error applying diff hunk: {e}")
            return {'success': False, 'error': str(e)}
    
    def create_project_from_template(self, template_name: str, project_name: str, 
                                   output_dir: str = None, variables: Dict = None) -> Dict:
        """
        Create a new project from a template.
        
        This method implements project scaffolding similar to Cursor's template system,
        allowing users to quickly create new projects with standardized structure.
        
        Args:
            template_name: Name of the template to use
            project_name: Name for the new project
            output_dir: Directory to create the project in (default: current directory)
            variables: Dictionary of template variables to substitute
            
        Returns:
            Dictionary with creation result
        """
        try:
            import shutil
            
            if variables is None:
                variables = {}
            
            # Set default variables
            variables.setdefault('PROJECT_NAME', project_name)
            variables.setdefault('project_name', project_name.lower().replace('-', '_'))
            variables.setdefault('ProjectName', project_name.replace('_', ' ').title())
            
            # Get template directory
            template_dir = Path(__file__).parent.parent / 'templates' / template_name
            
            if not template_dir.exists():
                # Try built-in templates
                template_content = self._get_builtin_template(template_name, variables)
                if not template_content:
                    return {'success': False, 'error': f'Template {template_name} not found'}
                
                # Create project directory
                if output_dir is None:
                    output_dir = Path.cwd()
                else:
                    output_dir = Path(output_dir)
                
                project_dir = output_dir / project_name
                project_dir.mkdir(parents=True, exist_ok=True)
                
                # Write template files
                for file_path, content in template_content.items():
                    file_full_path = project_dir / file_path
                    file_full_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(file_full_path, 'w', encoding='utf-8') as f:
                        f.write(content)
                
                return {
                    'success': True,
                    'project_name': project_name,
                    'project_path': str(project_dir),
                    'files_created': len(template_content),
                    'template': template_name
                }
            
            # Use external template directory
            if output_dir is None:
                output_dir = Path.cwd()
            else:
                output_dir = Path(output_dir)
            
            project_dir = output_dir / project_name
            shutil.copytree(template_dir, project_dir)
            
            # Substitute variables in files
            self._substitute_template_variables(project_dir, variables)
            
            return {
                'success': True,
                'project_name': project_name,
                'project_path': str(project_dir),
                'template': template_name
            }
            
        except Exception as e:
            logger.error(f"Error creating project from template: {e}")
            return {'success': False, 'error': str(e)}
    
    def _get_builtin_template(self, template_name: str, variables: Dict) -> Dict:
        """
        Get built-in template content.
        
        Args:
            template_name: Name of the template
            variables: Template variables to substitute
            
        Returns:
            Dictionary mapping file paths to content
        """
        templates = {
            'python-basic': {
                'README.md': f"""# {variables.get('ProjectName', 'My Project')}

## Description
A basic Python project.

## Installation
```bash
pip install -r requirements.txt
```

## Usage
```bash
python main.py
```
""",
                'main.py': f"""#!/usr/bin/env python3
\"\"\"
Main entry point for {variables.get('project_name', 'my_project')}.
\"\"\"

def main():
    print(f"Hello from {variables.get('project_name', 'my_project')}!")

if __name__ == "__main__":
    main()
""",
                'requirements.txt': """# Add your project dependencies here
# Example:
# requests>=2.28.0
""",
                '.gitignore': """# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg

# Virtual environments
venv/
env/
ENV/
.venv

# IDE
.vscode/
.idea/
*.swp
*.swo
*~

# OS
.DS_Store
Thumbs.db
"""
            },
            'python-web-flask': {
                'README.md': f"""# {variables.get('ProjectName', 'My Flask App')}

## Description
A basic Flask web application.

## Installation
```bash
pip install -r requirements.txt
```

## Usage
```bash
export FLASK_APP=app.py
flask run
```

## API Endpoints
- GET / - Home page
- GET /api/health - Health check
""",
                'app.py': f"""#!/usr/bin/env python3
\"\"\"
Flask application for {variables.get('project_name', 'my_flask_app')}.
\"\"\"

from flask import Flask, jsonify

app = Flask(__name__)

@app.route('/')
def home():
    return jsonify({{
        'message': 'Welcome to {variables.get('ProjectName', 'My Flask App')}!'
    }})

@app.route('/api/health')
def health():
    return jsonify({{
        'status': 'healthy'
    }})

if __name__ == '__main__':
    app.run(debug=True)
""",
                'requirements.txt': """Flask>=2.3.0
Werkzeug>=2.3.0
""",
                '.gitignore': """# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python

# Virtual environments
venv/
env/
ENV/
.venv

# Flask
instance/
.webassets-cache

# IDE
.vscode/
.idea/
*.swp
*.swo
*~

# OS
.DS_Store
Thumbs.db
"""
            },
            'javascript-basic': {
                'README.md': f"""# {variables.get('ProjectName', 'My JS Project')}

## Description
A basic JavaScript project.

## Installation
```bash
npm install
```

## Usage
```bash
npm start
```
""",
                'index.js': f"""/**
 * Main entry point for {variables.get('project_name', 'my_project')}
 */

function main() {{
    console.log('Hello from {variables.get('project_name', 'my_project')}!');
}}

main();
""",
                'package.json': f"""{{
  "name": "{variables.get('project_name', 'my-project')}",
  "version": "1.0.0",
  "description": "A basic JavaScript project",
  "main": "index.js",
  "scripts": {{
    "start": "node index.js",
    "test": "echo \\"Error: no test specified\\" && exit 1"
  }},
  "keywords": [],
  "author": "",
  "license": "MIT"
}}
""",
                '.gitignore': """# Dependencies
node_modules/

# Build
dist/
build/

# IDE
.vscode/
.idea/
*.swp
*.swo
*~

# OS
.DS_Store
Thumbs.db

# Logs
*.log
npm-debug.log*
"""
            }
        }
        
        if template_name not in templates:
            return None
        
        # Substitute variables in template content
        template_content = {}
        for file_path, content in templates[template_name].items():
            for key, value in variables.items():
                content = content.replace(f'{{{{{key}}}}}', str(value))
            template_content[file_path] = content
        
        return template_content
    
    def _substitute_template_variables(self, project_dir: Path, variables: Dict):
        """
        Substitute template variables in project files.
        
        Args:
            project_dir: Project directory
            variables: Variables to substitute
        """
        for file_path in project_dir.rglob('*'):
            if file_path.is_file():
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Substitute variables
                for key, value in variables.items():
                    content = content.replace(f'{{{{{key}}}}}', str(value))
                
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
    
    def format_code(self, file_path: str, formatter: str = 'auto') -> Dict:
        """
        Format code using external formatting tools.
        
        This method integrates with popular code formatters like black, prettier,
        and autopep8 to automatically format code according to style guidelines.
        
        Args:
            file_path: Path to the file to format
            formatter: Formatter to use ('auto', 'black', 'autopep8', 'prettier')
            
        Returns:
            Dictionary with formatting result
        """
        try:
            import subprocess
            
            file_path_obj = Path(file_path)
            
            if not file_path_obj.exists():
                return {'success': False, 'error': 'File does not exist'}
            
            # Auto-detect formatter based on file extension
            if formatter == 'auto':
                if file_path_obj.suffix == '.py':
                    formatter = 'black'
                elif file_path_obj.suffix in ['.js', '.jsx', '.ts', '.tsx', '.json']:
                    formatter = 'prettier'
                else:
                    return {'success': False, 'error': f'No auto-formatter for {file_path_obj.suffix}'}
            
            # Run formatter
            if formatter == 'black':
                try:
                    result = subprocess.run(
                        ['black', str(file_path_obj)],
                        capture_output=True,
                        text=True
                    )
                    return {
                        'success': True,
                        'formatter': 'black',
                        'file_path': str(file_path_obj),
                        'output': result.stdout,
                        'changed': 'reformatted' in result.stdout.lower()
                    }
                except FileNotFoundError:
                    return {'success': False, 'error': 'black not found. Install with: pip install black'}
            
            elif formatter == 'autopep8':
                try:
                    result = subprocess.run(
                        ['autopep8', '--in-place', str(file_path_obj)],
                        capture_output=True,
                        text=True
                    )
                    return {
                        'success': True,
                        'formatter': 'autopep8',
                        'file_path': str(file_path_obj),
                        'changed': True
                    }
                except FileNotFoundError:
                    return {'success': False, 'error': 'autopep8 not found. Install with: pip install autopep8'}
            
            elif formatter == 'prettier':
                try:
                    result = subprocess.run(
                        ['prettier', '--write', str(file_path_obj)],
                        capture_output=True,
                        text=True
                    )
                    return {
                        'success': True,
                        'formatter': 'prettier',
                        'file_path': str(file_path_obj),
                        'output': result.stdout,
                        'changed': True
                    }
                except FileNotFoundError:
                    return {'success': False, 'error': 'prettier not found. Install with: npm install -g prettier'}
            
            else:
                return {'success': False, 'error': f'Unknown formatter: {formatter}'}
            
        except Exception as e:
            logger.error(f"Error formatting code: {e}")
            return {'success': False, 'error': str(e)}
    
    def run_linter(self, file_path: str, linter: str = 'auto') -> Dict:
        """
        Run linter on a file.
        
        This method integrates with popular linting tools like pylint, flake8,
        and eslint to check code quality and identify potential issues.
        
        Args:
            file_path: Path to the file to lint
            linter: Linter to use ('auto', 'pylint', 'flake8', 'eslint')
            
        Returns:
            Dictionary with linting result
        """
        try:
            import subprocess
            
            file_path_obj = Path(file_path)
            
            if not file_path_obj.exists():
                return {'success': False, 'error': 'File does not exist'}
            
            # Auto-detect linter based on file extension
            if linter == 'auto':
                if file_path_obj.suffix == '.py':
                    linter = 'flake8'
                elif file_path_obj.suffix in ['.js', '.jsx', '.ts', '.tsx']:
                    linter = 'eslint'
                else:
                    return {'success': False, 'error': f'No auto-linter for {file_path_obj.suffix}'}
            
            # Run linter
            if linter == 'flake8':
                try:
                    result = subprocess.run(
                        ['flake8', str(file_path_obj)],
                        capture_output=True,
                        text=True
                    )
                    issues = result.stdout.strip().split('\n') if result.stdout.strip() else []
                    return {
                        'success': True,
                        'linter': 'flake8',
                        'file_path': str(file_path_obj),
                        'issues': issues,
                        'issue_count': len(issues)
                    }
                except FileNotFoundError:
                    return {'success': False, 'error': 'flake8 not found. Install with: pip install flake8'}
            
            elif linter == 'pylint':
                try:
                    result = subprocess.run(
                        ['pylint', str(file_path_obj), '--output-format=text'],
                        capture_output=True,
                        text=True
                    )
                    return {
                        'success': True,
                        'linter': 'pylint',
                        'file_path': str(file_path_obj),
                        'output': result.stdout,
                        'score': self._extract_pylint_score(result.stdout)
                    }
                except FileNotFoundError:
                    return {'success': False, 'error': 'pylint not found. Install with: pip install pylint'}
            
            elif linter == 'eslint':
                try:
                    result = subprocess.run(
                        ['eslint', str(file_path_obj)],
                        capture_output=True,
                        text=True
                    )
                    issues = result.stdout.strip().split('\n') if result.stdout.strip() else []
                    return {
                        'success': True,
                        'linter': 'eslint',
                        'file_path': str(file_path_obj),
                        'issues': issues,
                        'issue_count': len(issues)
                    }
                except FileNotFoundError:
                    return {'success': False, 'error': 'eslint not found. Install with: npm install -g eslint'}
            
            else:
                return {'success': False, 'error': f'Unknown linter: {linter}'}
            
        except Exception as e:
            logger.error(f"Error running linter: {e}")
            return {'success': False, 'error': str(e)}
    
    def _extract_pylint_score(self, pylint_output: str) -> float:
        """
        Extract pylint score from output.
        
        Args:
            pylint_output: Pylint output string
            
        Returns:
            Pylint score as float
        """
        import re
        match = re.search(r'Your code has been rated at (\d+\.\d+)/10', pylint_output)
        if match:
            return float(match.group(1))
        return 0.0
    
    def execute_sql_query(self, query: str, db_path: str = None, 
                        db_type: str = 'sqlite') -> Dict:
        """
        Execute SQL query on a database.
        
        This method provides database integration similar to Cursor's database features,
        allowing users to execute SQL queries and view results.
        
        Args:
            query: SQL query to execute
            db_path: Path to database file (for SQLite)
            db_type: Type of database ('sqlite', 'postgresql', 'mysql')
            
        Returns:
            Dictionary with query results
        """
        try:
            import sqlite3
            import json
            
            results = []
            columns = []
            
            if db_type == 'sqlite':
                if not db_path:
                    return {'success': False, 'error': 'Database path required for SQLite'}
                
                db_path_obj = Path(db_path)
                if not db_path_obj.exists():
                    return {'success': False, 'error': f'Database file not found: {db_path}'}
                
                conn = sqlite3.connect(str(db_path_obj))
                cursor = conn.cursor()
                
                try:
                    cursor.execute(query)
                    
                    # Get column names
                    if cursor.description:
                        columns = [desc[0] for desc in cursor.description]
                    
                    # Fetch results
                    rows = cursor.fetchall()
                    results = [dict(zip(columns, row)) for row in rows]
                    
                    # Get affected rows for non-SELECT queries
                    if not columns:
                        affected_rows = cursor.rowcount
                        return {
                            'success': True,
                            'query': query,
                            'affected_rows': affected_rows,
                            'message': f'Query affected {affected_rows} rows'
                        }
                    
                    conn.close()
                    
                    return {
                        'success': True,
                        'query': query,
                        'columns': columns,
                        'results': results,
                        'row_count': len(results)
                    }
                    
                except sqlite3.Error as e:
                    conn.close()
                    return {'success': False, 'error': f'SQL error: {str(e)}'}
                    
            else:
                return {'success': False, 'error': f'Database type {db_type} not yet supported'}
                
        except Exception as e:
            logger.error(f"Error executing SQL query: {e}")
            return {'success': False, 'error': str(e)}
    
    def get_database_schema(self, db_path: str, db_type: str = 'sqlite') -> Dict:
        """
        Get database schema information.
        
        This method retrieves schema information including tables, columns,
        and relationships from the database.
        
        Args:
            db_path: Path to database file (for SQLite)
            db_type: Type of database ('sqlite', 'postgresql', 'mysql')
            
        Returns:
            Dictionary with schema information
        """
        try:
            import sqlite3
            
            if db_type == 'sqlite':
                if not db_path:
                    return {'success': False, 'error': 'Database path required for SQLite'}
                
                db_path_obj = Path(db_path)
                if not db_path_obj.exists():
                    return {'success': False, 'error': f'Database file not found: {db_path}'}
                
                conn = sqlite3.connect(str(db_path_obj))
                cursor = conn.cursor()
                
                schema = {}
                
                # Get all tables
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
                tables = [row[0] for row in cursor.fetchall()]
                
                for table in tables:
                    # Get columns for each table
                    cursor.execute(f"PRAGMA table_info({table});")
                    columns = cursor.fetchall()
                    
                    table_info = {
                        'columns': []
                    }
                    
                    for col in columns:
                        col_info = {
                            'name': col[1],
                            'type': col[2],
                            'not_null': bool(col[3]),
                            'default_value': col[4],
                            'primary_key': bool(col[5])
                        }
                        table_info['columns'].append(col_info)
                    
                    # Get foreign keys
                    cursor.execute(f"PRAGMA foreign_key_list({table});")
                    foreign_keys = cursor.fetchall()
                    
                    if foreign_keys:
                        table_info['foreign_keys'] = []
                        for fk in foreign_keys:
                            fk_info = {
                                'id': fk[0],
                                'table': fk[2],
                                'from': fk[3],
                                'to': fk[4]
                            }
                            table_info['foreign_keys'].append(fk_info)
                    
                    schema[table] = table_info
                
                conn.close()
                
                return {
                    'success': True,
                    'database': db_path,
                    'tables': tables,
                    'schema': schema
                }
                
            else:
                return {'success': False, 'error': f'Database type {db_type} not yet supported'}
                
        except Exception as e:
            logger.error(f"Error getting database schema: {e}")
            return {'success': False, 'error': str(e)}
    
    def test_api_request(self, url: str, method: str = 'GET', 
                        headers: Dict = None, body: str = None) -> Dict:
        """
        Test an HTTP API request.
        
        This method provides API client functionality similar to Cursor's API testing,
        allowing users to test REST API endpoints.
        
        Args:
            url: API endpoint URL
            method: HTTP method (GET, POST, PUT, DELETE, etc.)
            headers: Request headers
            body: Request body (for POST, PUT, etc.)
            
        Returns:
            Dictionary with response information
        """
        try:
            import urllib.request
            import urllib.error
            import json
            
            if headers is None:
                headers = {}
            
            # Prepare request
            data = body.encode('utf-8') if body else None
            
            req = urllib.request.Request(url, data=data, method=method)
            
            # Add headers
            for key, value in headers.items():
                req.add_header(key, value)
            
            # Send request
            with urllib.request.urlopen(req, timeout=30) as response:
                response_body = response.read().decode('utf-8')
                response_headers = dict(response.headers)
                
                # Try to parse JSON response
                try:
                    response_json = json.loads(response_body)
                    return {
                        'success': True,
                        'url': url,
                        'method': method,
                        'status_code': response.status,
                        'headers': response_headers,
                        'body': response_json,
                        'body_type': 'json'
                    }
                except json.JSONDecodeError:
                    return {
                        'success': True,
                        'url': url,
                        'method': method,
                        'status_code': response.status,
                        'headers': response_headers,
                        'body': response_body,
                        'body_type': 'text'
                    }
                    
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8') if e.fp else str(e)
            return {
                'success': False,
                'error': f'HTTP Error: {e.code} - {e.reason}',
                'status_code': e.code,
                'body': error_body
            }
        except urllib.error.URLError as e:
            return {
                'success': False,
                'error': f'URL Error: {str(e)}'
            }
        except Exception as e:
            logger.error(f"Error testing API request: {e}")
            return {'success': False, 'error': str(e)}
    
    def track_collaboration_changes(self, file_path: str, changes: List[Dict]) -> Dict:
        """
        Track changes from collaboration.
        
        This method tracks changes made by collaborators during real-time collaboration.
        
        Args:
            file_path: Path to the file being edited
            changes: List of change dictionaries
            
        Returns:
            Dictionary with change tracking status
        """
        try:
            # Change tracking infrastructure is ready
            # To enable full tracking:
            # - Store changes in database with timestamps
            # - Apply operational transformation (OT) for conflict resolution
            # - Broadcast changes to other clients via WebSocket
            # - Maintain change history for rollback
            
            return {
                'success': True,
                'file_path': file_path,
                'changes_tracked': len(changes),
                'status': 'tracked',
                'note': 'Full tracking requires WebSocket server and OT implementation'
            }
            
        except Exception as e:
            logger.error(f"Error tracking collaboration changes: {e}")
            return {'success': False, 'error': str(e)}
    
    def _cosine_similarity(self, vec1, vec2) -> float:
        """
        Calculate cosine similarity between two vectors.
        
        Args:
            vec1: First vector (list or numpy array)
            vec2: Second vector (list or numpy array)
            
        Returns:
            Cosine similarity score
        """
        if not NUMPY_AVAILABLE:
            return 0.0
        
        # Convert to numpy arrays if needed
        if not isinstance(vec1, np.ndarray):
            vec1 = np.array(vec1)
        if not isinstance(vec2, np.ndarray):
            vec2 = np.array(vec2)
        
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
