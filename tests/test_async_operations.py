"""
Unit tests for async operations module.
"""

import asyncio
import unittest

from aider.async_operations import (
    AsyncOperationManager,
    AsyncOperationResult,
    AsyncResourcePool,
    async_context_manager,
    async_operation,
    gather_with_error_handling,
    get_async_manager,
)


class TestAsyncOperationResult(unittest.TestCase):
    """Test async operation result dataclass."""

    def test_async_operation_result_creation(self):
        """Test creating an async operation result."""
        result = AsyncOperationResult(
            success=True,
            result=42,
            duration_ms=100.0,
        )
        
        self.assertTrue(result.success)
        self.assertEqual(result.result, 42)


class TestAsyncOperationManager(unittest.TestCase):
    """Test async operation manager."""

    def setUp(self):
        """Set up test fixtures."""
        self.manager = AsyncOperationManager()
    
    def test_run_async(self):
        """Test running an async operation."""
        async def test_operation():
            await asyncio.sleep(0.01)
            return 42
        
        async def test():
            result = await self.manager.run_async(test_operation())
            return result
        
        result = asyncio.run(test())
        
        self.assertTrue(result.success)
        self.assertEqual(result.result, 42)
    
    def test_run_async_sync(self):
        """Test running an async operation synchronously."""
        async def test_operation():
            await asyncio.sleep(0.01)
            return 42
        
        result = self.manager.run_async_sync(test_operation())
        
        self.assertTrue(result.success)
        self.assertEqual(result.result, 42)
    
    def test_run_async_with_error(self):
        """Test running an async operation that raises an error."""
        async def failing_operation():
            await asyncio.sleep(0.01)
            raise ValueError("Test error")
        
        result = self.manager.run_async_sync(failing_operation())
        
        self.assertFalse(result.success)
        self.assertIsNotNone(result.error)
    
    def test_get_result(self):
        """Test getting operation result."""
        async def test_operation():
            return 42
        
        self.manager.run_async_sync(test_operation(), "test_op")
        
        result = self.manager.get_result("test_op")
        
        self.assertIsNotNone(result)
        self.assertTrue(result.success)


class TestAsyncResourcePool(unittest.TestCase):
    """Test async resource pool."""

    def test_async_resource_pool(self):
        """Test async resource pool."""
        async def test():
            pool = AsyncResourcePool(max_size=3)
            
            # Add resources
            await pool.add_resource("resource1")
            await pool.add_resource("resource2")
            
            # Acquire and release
            resource = await pool.acquire()
            self.assertIsNotNone(resource)
            
            await pool.release(resource)
            
            # Get stats
            stats = await pool.get_stats()
            self.assertEqual(stats["max_size"], 3)
        
        asyncio.run(test())


class TestAsyncOperationDecorator(unittest.TestCase):
    """Test async operation decorator."""

    def test_async_operation_decorator(self):
        """Test async operation decorator."""
        @async_operation("test_op")
        async def test_func():
            return 42
        
        result = asyncio.run(test_func())
        
        self.assertEqual(result, 42)


class TestGatherWithErrorHandling(unittest.TestCase):
    """Test gather with error handling."""

    def test_gather_with_error_handling(self):
        """Test gathering coroutines with error handling."""
        async def test():
            async def op1():
                return 1
            
            async def op2():
                return 2
            
            results = await gather_with_error_handling(op1(), op2())
            
            self.assertEqual(len(results), 2)
    
    def test_gather_with_error_handling_with_error(self):
        """Test gathering coroutines with error handling when one fails."""
        async def test():
            async def op1():
                return 1
            
            async def failing_op():
                raise ValueError("Test error")
            
            results = await gather_with_error_handling(op1(), failing_op())
            
            self.assertEqual(len(results), 2)


class TestGlobalAsyncManager(unittest.TestCase):
    """Test global async manager instance."""

    def test_get_async_manager(self):
        """Test getting global async manager."""
        manager = get_async_manager()
        self.assertIsNotNone(manager)
        
        # Should return same instance
        manager2 = get_async_manager()
        self.assertIs(manager, manager2)


if __name__ == "__main__":
    unittest.main()
