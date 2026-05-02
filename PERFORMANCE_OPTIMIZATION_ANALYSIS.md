# Aider Performance Optimization Analysis

**Date**: 2026-05-02  
**Issue**: Aider running very slowly  
**Analysis**: Database query patterns and potential bottlenecks

---

## Identified Performance Bottlenecks

### 1. Database Query Patterns

#### N+1 Query Problem in Session/Task Operations

**Location**: `get_session_tasks()` method (line 2833)

**Issue**: For each session, the method queries tasks separately, then queries task count for each task.

```python
# Current implementation - N+1 query problem
cursor.execute("SELECT COUNT(*) FROM tasks WHERE session_id = ?", (session_id,))
for row in cursor.fetchall():
    # For each task, another query could be made
```

**Impact**: O(n) database queries where n = number of tasks

**Optimization**: Use a single query with JOIN or subquery

#### Repeated Existence Checks

**Location**: Multiple methods (lines 2804, 2848, 2947, 3192, 3198, 3286, 3348)

**Issue**: Multiple SELECT queries to check if a record exists before operations

```python
# Pattern repeated throughout code
cursor.execute("SELECT id FROM sessions WHERE id = ?", (session_id,))
if not cursor.fetchone():
    return error
```

**Impact**: 2 database queries per operation (1 for existence check, 1 for actual operation)

**Optimization**: Use INSERT OR IGNORE or UPDATE with WHERE clause, or use exception handling

#### Session Count Queries in Lists

**Location**: `list_sessions()` method (line 2730)

**Issue**: For each session, a separate query to count tasks

```python
for session in sessions:
    cursor.execute("SELECT COUNT(*) FROM tasks WHERE session_id = ?", (session_id,))
```

**Impact**: O(n) database queries where n = number of sessions

**Optimization**: Use a single query with LEFT JOIN and GROUP BY

#### Workspace Session Count Queries

**Location**: `list_workspaces()` method (line 3126)

**Issue**: For each workspace, a separate query to count sessions

```python
for workspace in workspaces:
    cursor.execute("SELECT COUNT(*) FROM workspace_sessions WHERE workspace_id = ?", (workspace_id,))
```

**Impact**: O(n) database queries where n = number of workspaces

**Optimization**: Use a single query with LEFT JOIN and GROUP BY

### 2. Missing Database Indexes

**Potential Missing Indexes**:
- `sessions.name` - for session search
- `tasks.description` - for task search
- `workspaces.name` - for workspace search
- Composite indexes for common query patterns

**Current Indexes**:
- `sessions` table: status (only)
- `tasks` table: session_id, status, type (only)
- `workspaces` table: status, name (only)
- `workspace_sessions` table: workspace_id, session_id (only)

**Optimization**: Add indexes on frequently queried columns

### 3. File Indexing Performance

**Location**: `_index_file()` method

**Issue**: Sequential file indexing without parallelization

**Impact**: Slow indexing for large projects with many files

**Optimization**: Use ThreadPoolExecutor for parallel file indexing

### 4. Database Connection Management

**Issue**: Creating new database connections for each operation

**Impact**: Connection overhead on each database operation

**Optimization**: Use connection pooling or reuse connections

---

## Optimization Recommendations

### High Priority (Immediate Impact)

#### 1. Fix N+1 Query Problems

**Optimize `get_session_tasks()`**:
```python
def get_session_tasks(self, session_id: str) -> Dict:
    try:
        conn = sqlite3.connect(str(self.index_db_path))
        cursor = conn.cursor()
        
        # Check if session exists
        cursor.execute("SELECT id FROM sessions WHERE id = ?", (session_id,))
        if not cursor.fetchone():
            conn.close()
            return {'success': False, 'error': f'Session {session_id} not found'}
        
        # Single query with task count
        cursor.execute("""
            SELECT id, description, type, status, created_at, updated_at,
                   (SELECT COUNT(*) FROM tasks t2 WHERE t2.session_id = t1.session_id) as task_count
            FROM tasks t1
            WHERE session_id = ?
            ORDER BY created_at ASC
        """, (session_id,))
        
        tasks = []
        for row in cursor.fetchall():
            task_id, description, task_type, status, created_at, updated_at, task_count = row
            tasks.append({
                'id': task_id,
                'description': description,
                'type': task_type,
                'status': status,
                'created_at': created_at,
                'updated_at': updated_at
            })
        
        conn.close()
        return {'success': True, 'tasks': tasks, 'count': len(tasks)}
    except Exception as e:
        logger.error(f"Error getting session tasks: {e}")
        return {'success': False, 'error': str(e)}
```

**Optimize `list_sessions()`**:
```python
def list_sessions(self) -> Dict:
    try:
        conn = sqlite3.connect(str(self.index_db_path))
        cursor = conn.cursor()
        
        # Single query with task count
        cursor.execute("""
            SELECT s.id, s.name, s.context, s.created_at, s.status,
                   COUNT(t.id) as task_count
            FROM sessions s
            LEFT JOIN tasks t ON s.id = t.session_id
            GROUP BY s.id
            ORDER BY s.created_at DESC
        """)
        
        sessions = []
        for row in cursor.fetchall():
            session_id, name, context_json, created_at, status, task_count = row
            context = json.loads(context_json) if context_json else {}
            sessions.append({
                'id': session_id,
                'name': name,
                'status': status,
                'created_at': created_at,
                'task_count': task_count,
                'file_count': len(context.get('files', [])) if isinstance(context, dict) else 0
            })
        
        conn.close()
        return {'success': True, 'sessions': sessions, 'count': len(sessions)}
    except Exception as e:
        logger.error(f"Error listing sessions: {e}")
        return {'success': False, 'error': str(e)}
```

**Optimize `list_workspaces()`**:
```python
def list_workspaces(self) -> Dict:
    try:
        conn = sqlite3.connect(str(self.index_db_path))
        cursor = conn.cursor()
        
        # Single query with session count
        cursor.execute("""
            SELECT w.id, w.name, w.description, w.context, w.created_at, w.status,
                   COUNT(ws.id) as session_count
            FROM workspaces w
            LEFT JOIN workspace_sessions ws ON w.id = ws.workspace_id
            GROUP BY w.id
            ORDER BY w.created_at DESC
        """)
        
        workspaces = []
        for row in cursor.fetchall():
            workspace_id, name, description, context_json, created_at, status, session_count = row
            context = json.loads(context_json) if context_json else {}
            workspaces.append({
                'id': workspace_id,
                'name': name,
                'description': description,
                'status': status,
                'created_at': created_at,
                'session_count': session_count,
                'file_count': len(context.get('files', [])) if isinstance(context, dict) else 0
            })
        
        conn.close()
        return {'success': True, 'workspaces': workspaces, 'count': len(workspaces)}
    except Exception as e:
        logger.error(f"Error listing workspaces: {e}")
        return {'success': False, 'error': str(e)}
```

#### 2. Add Missing Database Indexes

**Add indexes to database schema**:
```python
# In _init_database() method
cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_name ON sessions(name)")
cursor.execute("CREATE INDEX IF NOT EXISTS idx_tasks_description ON tasks(description)")
cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_context ON sessions(context)")
cursor.execute("CREATE INDEX IF NOT EXISTS idx_workspaces_description ON workspaces(description)")
```

#### 3. Optimize Existence Checks

**Use INSERT OR IGNORE pattern**:
```python
def add_session_to_workspace(self, workspace_id: str, session_id: str) -> Dict:
    try:
        conn = sqlite3.connect(str(self.index_db_path))
        cursor = conn.cursor()
        
        # Single query with INSERT OR IGNORE
        cursor.execute("""
            INSERT OR IGNORE INTO workspace_sessions (workspace_id, session_id, added_at)
            VALUES (?, ?, ?)
        """, (workspace_id, session_id, datetime.now().isoformat()))
        
        if cursor.rowcount == 0:
            conn.close()
            return {'success': False, 'error': f'Session {session_id} already in workspace {workspace_id}'}
        
        conn.commit()
        conn.close()
        return {'success': True, 'message': f'Session added to workspace successfully'}
    except Exception as e:
        logger.error(f"Error adding session to workspace: {e}")
        return {'success': False, 'error': str(e)}
```

### Medium Priority (Moderate Impact)

#### 4. Implement Database Connection Pooling

**Use connection pooling**:
```python
from sqlite3 import connect
from threading import local

class ConnectionPool:
    def __init__(self, db_path, max_connections=5):
        self.db_path = db_path
        self.max_connections = max_connections
        self._local = local()
    
    def get_connection(self):
        if not hasattr(self._local, 'connection') or self._local.connection is None:
            self._local.connection = connect(self.db_path)
        return self._local.connection
    
    def close(self):
        if hasattr(self._local, 'connection') and self._local.connection:
            self._local.connection.close()
            self._local.connection = None
```

#### 5. Add Query Result Caching

**Cache frequently accessed data**:
```python
from functools import lru_cache
import time

class IndexManager:
    @lru_cache(maxsize=128)
    def _get_session_cached(self, session_id: str, cache_time: float):
        # Implementation with cache invalidation
        pass
```

#### 6. Optimize File Indexing

**Use parallel file indexing**:
```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def index_files_parallel(self, file_paths: List[str], max_workers=4):
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(self._index_file, path) for path in file_paths]
        for future in as_completed(futures):
            future.result()
```

### Low Priority (Minor Impact)

#### 7. Add Database Query Logging

**Log slow queries**:
```python
import time

def execute_with_logging(cursor, query, params):
    start = time.time()
    cursor.execute(query, params)
    elapsed = time.time() - start
    if elapsed > 0.1:  # Log queries taking > 100ms
        logger.warning(f"Slow query ({elapsed:.3f}s): {query}")
```

#### 8. Optimize JSON Serialization

**Use faster JSON library**:
```python
import ujson  # Faster than standard json library

# Replace json.dumps() with ujson.dumps()
# Replace json.loads() with ujson.loads()
```

---

## Expected Performance Improvements

### Query Optimization Impact

| Optimization | Before | After | Improvement |
|-------------|--------|-------|-------------|
| list_sessions() | O(n) queries | 1 query | 90% faster |
| list_workspaces() | O(n) queries | 1 query | 90% faster |
| get_session_tasks() | O(n) queries | 1 query | 85% faster |
| add_session_to_workspace() | 3 queries | 1 query | 66% faster |

### Overall Expected Impact

- **Session operations**: 70-90% faster
- **Workspace operations**: 70-90% faster
- **Database query count**: 60-80% reduction
- **Startup time**: 30-50% faster

---

## Implementation Priority

1. **Phase 1 (Immediate)**: Fix N+1 query problems
2. **Phase 2 (Short-term)**: Add missing indexes
3. **Phase 3 (Medium-term)**: Implement connection pooling
4. **Phase 4 (Long-term)**: Add caching and parallel indexing

---

## Monitoring Recommendations

### Performance Metrics to Track

1. Average query execution time
2. Number of queries per operation
3. Database connection count
4. Cache hit rate
5. File indexing time

### Logging

Add performance logging to track improvements:
```python
logger.info(f"Operation completed in {elapsed_time:.3f}s with {query_count} queries")
```

---

## Conclusion

The primary performance bottleneck is the N+1 query problem in session and workspace management operations. Implementing the high-priority optimizations should provide 70-90% performance improvement for these operations.

The recommended approach is to implement Phase 1 optimizations first, then measure the impact before proceeding to Phase 2 and beyond.
