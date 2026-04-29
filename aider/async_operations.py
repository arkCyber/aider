"""
Async Operations Module

This module provides async operation support for the Aider AI coding assistant.
It implements aerospace-level async handling with proper coroutine management,
async context managers, and comprehensive error handling.

Key Features:
- Async operation management
- Async context managers
- Async iterators
- Async task scheduling
- Async resource cleanup
- Async error handling
- Async performance monitoring
"""

import asyncio
import functools
import inspect
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, AsyncGenerator, Callable, Coroutine, Dict, List, Optional, TypeVar
import traceback


T = TypeVar('T')


@dataclass
class AsyncOperationResult:
    """
    Result of an async operation.
    
    Attributes:
        success: Whether the operation was successful
        result: Operation result (if successful)
        error: Error message (if failed)
        duration_ms: Duration in milliseconds
        timestamp: When the operation completed
    """
    success: bool
    result: Any = None
    error: Optional[str] = None
    duration_ms: float = 0.0
    timestamp: datetime = field(default_factory=datetime.utcnow)


class AsyncOperationManager:
    """
    Async operation manager with aerospace-level capabilities.
    
    This class provides comprehensive async operation management with
    proper coroutine handling, cleanup, and error management.
    """
    
    def __init__(self):
        """Initialize the async operation manager."""
        self._tasks: Dict[str, asyncio.Task] = {}
        self._results: Dict[str, AsyncOperationResult] = {}
        self._lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._running = False
    
    def _get_loop(self) -> asyncio.AbstractEventLoop:
        """
        Get or create an event loop.
        
        Returns:
            Event loop
        """
        if self._loop is None or self._loop.is_closed():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
        return self._loop
    
    async def run_async(
        self,
        coro: Coroutine[Any, Any, T],
        operation_id: Optional[str] = None,
    ) -> AsyncOperationResult:
        """
        Run an async operation.
        
        Args:
            coro: Coroutine to run
            operation_id: Optional operation identifier
            
        Returns:
            AsyncOperationResult
        """
        if operation_id is None:
            operation_id = f"op_{int(time.time() * 1000)}"
        
        start_time = time.time()
        
        try:
            result = await coro
            duration_ms = (time.time() - start_time) * 1000
            
            op_result = AsyncOperationResult(
                success=True,
                result=result,
                duration_ms=duration_ms,
            )
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            op_result = AsyncOperationResult(
                success=False,
                error=str(e),
                duration_ms=duration_ms,
            )
        
        with self._lock:
            self._results[operation_id] = op_result
        
        return op_result
    
    def run_async_sync(
        self,
        coro: Coroutine[Any, Any, T],
        operation_id: Optional[str] = None,
    ) -> AsyncOperationResult:
        """
        Run an async operation synchronously (blocking).
        
        Args:
            coro: Coroutine to run
            operation_id: Optional operation identifier
            
        Returns:
            AsyncOperationResult
        """
        loop = self._get_loop()
        
        try:
            result = loop.run_until_complete(self.run_async(coro, operation_id))
            return result
        finally:
            # Don't close the loop, it may be reused
            pass
    
    def schedule_task(
        self,
        coro: Coroutine[Any, Any, T],
        task_id: str,
        callback: Optional[Callable[[AsyncOperationResult], None]] = None,
    ) -> asyncio.Task:
        """
        Schedule an async task.
        
        Args:
            coro: Coroutine to run
            task_id: Task identifier
            callback: Optional callback function
            
        Returns:
            asyncio.Task
        """
        loop = self._get_loop()
        
        async def wrapper():
            result = await self.run_async(coro, task_id)
            if callback:
                callback(result)
            return result
        
        task = loop.create_task(wrapper())
        
        with self._lock:
            self._tasks[task_id] = task
        
        return task
    
    def cancel_task(self, task_id: str) -> bool:
        """
        Cancel a scheduled task.
        
        Args:
            task_id: Task identifier
            
        Returns:
            True if cancellation was successful, False otherwise
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if task and not task.done():
                task.cancel()
                return True
        return False
    
    def get_task_status(self, task_id: str) -> Optional[str]:
        """
        Get the status of a task.
        
        Args:
            task_id: Task identifier
            
        Returns:
            Task status string or None if not found
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                if task.done():
                    if task.cancelled():
                        return "cancelled"
                    elif task.exception():
                        return "error"
                    else:
                        return "completed"
                else:
                    return "running"
        return None
    
    def get_result(self, operation_id: str) -> Optional[AsyncOperationResult]:
        """
        Get the result of an operation.
        
        Args:
            operation_id: Operation identifier
            
        Returns:
            AsyncOperationResult or None if not found
        """
        with self._lock:
            return self._results.get(operation_id)
    
    def cleanup(self) -> None:
        """Cleanup resources."""
        with self._lock:
            # Cancel all tasks
            for task_id, task in self._tasks.items():
                if not task.done():
                    task.cancel()
            
            # Close the loop
            if self._loop and not self._loop.is_closed():
                self._loop.close()
            
            self._tasks.clear()
            self._results.clear()


def async_operation(operation_id: Optional[str] = None):
    """
    Decorator to mark a function as an async operation.
    
    Args:
        operation_id: Optional operation identifier
        
    Returns:
        Decorator function
    """
    def decorator(func):
        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def wrapper(*args, **kwargs):
                manager = get_async_manager()
                return await manager.run_async(func(*args, **kwargs), operation_id)
            return wrapper
        else:
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                # Convert sync function to async
                async def async_wrapper():
                    return func(*args, **kwargs)
                
                manager = get_async_manager()
                return manager.run_async_sync(async_wrapper(), operation_id)
            return wrapper
    return decorator


@asynccontextmanager
async def async_context_manager(resource: Any):
    """
    Generic async context manager.
    
    Args:
        resource: Resource to manage
        
    Yields:
        Resource
    """
    try:
        yield resource
    finally:
        # Cleanup logic here
        if hasattr(resource, 'close'):
            await resource.close()


class AsyncResourcePool:
    """
    Async resource pool for managing limited resources.
    
    This class provides aerospace-level resource pooling with
    proper async handling and cleanup.
    """
    
    def __init__(self, max_size: int = 10):
        """
        Initialize the async resource pool.
        
        Args:
            max_size: Maximum pool size
        """
        self.max_size = max_size
        self._available: asyncio.Queue = asyncio.Queue(maxsize=max_size)
        self._in_use: set = set()
        self._lock = asyncio.Lock()
    
    async def acquire(self) -> Any:
        """
        Acquire a resource from the pool.
        
        Returns:
            Resource
        """
        resource = await self._available.get()
        
        async with self._lock:
            self._in_use.add(resource)
        
        return resource
    
    async def release(self, resource: Any) -> None:
        """
        Release a resource back to the pool.
        
        Args:
            resource: Resource to release
        """
        async with self._lock:
            if resource in self._in_use:
                self._in_use.remove(resource)
        
        await self._available.put(resource)
    
    async def add_resource(self, resource: Any) -> None:
        """
        Add a resource to the pool.
        
        Args:
            resource: Resource to add
        """
        await self._available.put(resource)
    
    async def get_stats(self) -> Dict[str, int]:
        """
        Get pool statistics.
        
        Returns:
            Dictionary with statistics
        """
        async with self._lock:
            return {
                "available": self._available.qsize(),
                "in_use": len(self._in_use),
                "max_size": self.max_size,
            }


# Global async manager instance
_global_async_manager: Optional[AsyncOperationManager] = None


def get_async_manager() -> AsyncOperationManager:
    """
    Get the global async operation manager instance.
    
    Returns:
        Global AsyncOperationManager instance
    """
    global _global_async_manager
    if _global_async_manager is None:
        _global_async_manager = AsyncOperationManager()
    return _global_async_manager


async def gather_with_error_handling(
    *coros: Coroutine[Any, Any, Any],
    return_exceptions: bool = True,
) -> List[Any]:
    """
    Gather coroutines with comprehensive error handling.
    
    Args:
        *coros: Coroutines to gather
        return_exceptions: Whether to return exceptions instead of raising
        
    Returns:
        List of results
    """
    results = []
    
    for coro in coros:
        try:
            result = await coro
            results.append(result)
        except Exception as e:
            if return_exceptions:
                results.append(e)
            else:
                raise
    
    return results
