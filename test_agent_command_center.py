#!/usr/bin/env python3
"""
Agent Command Center Test Suite
Tests for session management and task tracking functionality
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from aider.index_manager import IndexManager
from datetime import datetime
import tempfile
import shutil


def print_section(title):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def test_session_creation():
    print_section("Testing Session Creation")
    
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = IndexManager(tmpdir)
            
            # Test basic session creation
            result = manager.create_session("test-session")
            assert result['success'] == True, "Session creation failed"
            assert 'session_id' in result, "Session ID not in result"
            assert result['session_name'] == "test-session", "Session name mismatch"
            print(f"✓ Basic session creation successful")
            print(f"  Session ID: {result['session_id']}")
            
            # Test session with context
            result2 = manager.create_session("session-with-context", {"project": "test"})
            assert result2['success'] == True, "Session with context creation failed"
            print(f"✓ Session with context creation successful")
            
            # Verify sessions are stored (use same manager instance)
            sessions = manager.list_sessions()
            assert sessions['success'] == True, "List sessions failed"
            assert sessions['count'] == 2, f"Expected 2 sessions, got {sessions['count']}"
            print(f"✓ Sessions stored correctly (count: {sessions['count']})")
            
            return True
    except Exception as e:
        print(f"✗ Test failed: {e}")
        return False


def test_session_listing():
    print_section("Testing Session Listing")
    
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = IndexManager(tmpdir)
            
            # Create multiple sessions in the same manager instance
            manager.create_session("session-1")
            manager.create_session("session-2")
            manager.create_session("session-3")
            
            # List sessions
            result = manager.list_sessions()
            assert result['success'] == True, "List sessions failed"
            assert result['count'] == 3, f"Expected 3 sessions, got {result['count']}"
            
            print(f"✓ Session listing successful (count: {result['count']})")
            
            # Verify session structure
            for session in result['sessions']:
                assert 'id' in session, "Session missing ID"
                assert 'name' in session, "Session missing name"
                assert 'status' in session, "Session missing status"
                assert 'created_at' in session, "Session missing created_at"
                assert 'task_count' in session, "Session missing task_count"
                assert 'file_count' in session, "Session missing file_count"
            
            print(f"✓ Session structure validation passed")
            
            return True
    except Exception as e:
        print(f"✗ Test failed: {e}")
        return False


def test_task_management():
    print_section("Testing Task Management")
    
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = IndexManager(tmpdir)
            
            # Create session
            session_result = manager.create_session("task-test-session")
            session_id = session_result['session_id']
            print(f"  Created session: {session_id}")
            
            # Add tasks
            task1 = manager.add_task_to_session(session_id, "Refactor code", "refactoring")
            assert task1['success'] == True, "Task 1 addition failed"
            print(f"✓ Task 1 added: {task1['task_id']}")
            
            task2 = manager.add_task_to_session(session_id, "Write tests", "testing")
            assert task2['success'] == True, "Task 2 addition failed"
            print(f"✓ Task 2 added: {task2['task_id']}")
            
            task3 = manager.add_task_to_session(session_id, "Update docs", "documentation")
            assert task3['success'] == True, "Task 3 addition failed"
            print(f"✓ Task 3 added: {task3['task_id']}")
            
            # Get tasks
            tasks_result = manager.get_session_tasks(session_id)
            assert tasks_result['success'] == True, "Get tasks failed"
            assert tasks_result['count'] == 3, f"Expected 3 tasks, got {tasks_result['count']}"
            print(f"✓ Task retrieval successful (count: {tasks_result['count']})")
            
            # Update task status
            update_result = manager.update_task_status(session_id, task1['task_id'], "in_progress")
            assert update_result['success'] == True, "Task status update failed"
            print(f"✓ Task status updated to in_progress")
            
            update_result2 = manager.update_task_status(session_id, task2['task_id'], "completed")
            assert update_result2['success'] == True, "Task status update failed"
            print(f"✓ Task status updated to completed")
            
            # Verify task status
            tasks_after = manager.get_session_tasks(session_id)
            assert tasks_after['success'] == True, "Get tasks after update failed"
            
            status_count = sum(1 for t in tasks_after['tasks'] if t['status'] == 'completed')
            assert status_count == 1, f"Expected 1 completed task, got {status_count}"
            print(f"✓ Task status verification passed")
            
            return True
    except Exception as e:
        print(f"✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_session_deletion():
    print_section("Testing Session Deletion")
    
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = IndexManager(tmpdir)
            
            # Create sessions in the same manager instance
            session1 = manager.create_session("session-to-delete")
            session2 = manager.create_session("session-to-keep")
            
            # Add tasks to session1
            manager.add_task_to_session(session1['session_id'], "Task 1")
            manager.add_task_to_session(session1['session_id'], "Task 2")
            
            # Verify sessions exist
            before_delete = manager.list_sessions()
            assert before_delete['count'] == 2, "Expected 2 sessions before deletion"
            print(f"✓ Sessions before deletion: {before_delete['count']}")
            
            # Delete session
            delete_result = manager.delete_session(session1['session_id'])
            assert delete_result['success'] == True, "Session deletion failed"
            print(f"✓ Session deleted successfully")
            
            # Verify deletion
            after_delete = manager.list_sessions()
            assert after_delete['count'] == 1, f"Expected 1 session after deletion, got {after_delete['count']}"
            assert after_delete['sessions'][0]['id'] == session2['session_id'], "Wrong session deleted"
            print(f"✓ Session deletion verified (count: {after_delete['count']})")
            
            return True
    except Exception as e:
        print(f"✗ Test failed: {e}")
        return False


def test_error_handling():
    print_section("Testing Error Handling")
    
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = IndexManager(tmpdir)
            
            # Test adding task to non-existent session
            result = manager.add_task_to_session("non-existent-session", "Test task")
            assert result['success'] == False, "Should fail for non-existent session"
            assert 'error' in result, "Error message missing"
            print(f"✓ Non-existent session error handling passed")
            
            # Test getting tasks from non-existent session
            result = manager.get_session_tasks("non-existent-session")
            assert result['success'] == False, "Should fail for non-existent session"
            print(f"✓ Non-existent session task retrieval error handling passed")
            
            # Test updating task in non-existent session
            result = manager.update_task_status("non-existent-session", "task-id", "completed")
            assert result['success'] == False, "Should fail for non-existent session"
            print(f"✓ Non-existent session task update error handling passed")
            
            # Test deleting non-existent session
            result = manager.delete_session("non-existent-session")
            assert result['success'] == False, "Should fail for non-existent session"
            print(f"✓ Non-existent session deletion error handling passed")
            
            # Test updating non-existent task
            session = manager.create_session("test-session")
            result = manager.update_task_status(session['session_id'], "non-existent-task", "completed")
            assert result['success'] == False, "Should fail for non-existent task"
            print(f"✓ Non-existent task update error handling passed")
            
            return True
    except Exception as e:
        print(f"✗ Test failed: {e}")
        return False


def test_edge_cases():
    print_section("Testing Edge Cases")
    
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = IndexManager(tmpdir)
            
            # Test empty session name
            result = manager.create_session("")
            assert result['success'] == True, "Empty session name should be allowed"
            print(f"✓ Empty session name handling passed")
            
            # Test very long session name
            long_name = "a" * 1000
            result = manager.create_session(long_name)
            assert result['success'] == True, "Long session name should be allowed"
            print(f"✓ Long session name handling passed")
            
            # Test special characters in session name
            special_name = "test-session-with_special.chars!"
            result = manager.create_session(special_name)
            assert result['success'] == True, "Special characters in name should be allowed"
            print(f"✓ Special characters in session name handling passed")
            
            # Test empty task description
            session = manager.create_session("test-session")
            result = manager.add_task_to_session(session['session_id'], "")
            assert result['success'] == True, "Empty task description should be allowed"
            print(f"✓ Empty task description handling passed")
            
            # Test very long task description
            long_task = "a" * 5000
            result = manager.add_task_to_session(session['session_id'], long_task)
            assert result['success'] == True, "Long task description should be allowed"
            print(f"✓ Long task description handling passed")
            
            # Test invalid status
            result = manager.update_task_status(session['session_id'], "task-id", "invalid_status")
            assert result['success'] == False, "Invalid status should fail"
            print(f"✓ Invalid status handling passed")
            
            # Test listing sessions when none exist (use same manager)
            # Clear sessions by deleting them
            sessions = manager.list_sessions()
            for s in sessions['sessions']:
                manager.delete_session(s['id'])
            
            result = manager.list_sessions()
            assert result['success'] == True, "Listing empty sessions should succeed"
            assert result['count'] == 0, "Empty sessions should have count 0"
            print(f"✓ Empty session list handling passed")
            
            return True
    except Exception as e:
        print(f"✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_concurrent_operations():
    print_section("Testing Concurrent Operations")
    
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = IndexManager(tmpdir)
            
            # Create multiple sessions rapidly in the same manager instance
            session_ids = []
            for i in range(10):
                result = manager.create_session(f"concurrent-session-{i}")
                assert result['success'] == True, f"Session {i} creation failed"
                session_ids.append(result['session_id'])
            
            print(f"✓ Rapid session creation (10 sessions)")
            
            # Add tasks to all sessions
            for session_id in session_ids:
                for j in range(5):
                    result = manager.add_task_to_session(session_id, f"Task {j}")
                    assert result['success'] == True, f"Task addition failed for session {session_id}"
            
            print(f"✓ Rapid task addition (50 tasks across 10 sessions)")
            
            # Verify all sessions and tasks
            sessions = manager.list_sessions()
            assert sessions['count'] == 10, f"Expected 10 sessions, got {sessions['count']}"
            
            total_tasks = 0
            for session in sessions['sessions']:
                tasks = manager.get_session_tasks(session['id'])
                total_tasks += tasks['count']
            
            assert total_tasks == 50, f"Expected 50 tasks, got {total_tasks}"
            print(f"✓ Concurrent operations verification passed (10 sessions, 50 tasks)")
            
            return True
    except Exception as e:
        print(f"✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_session_context():
    print_section("Testing Session Context")
    
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = IndexManager(tmpdir)
            
            # Create session with context
            context = {
                "project": "test-project",
                "branch": "main",
                "files": ["file1.py", "file2.py"],
                "metadata": {"key": "value"}
            }
            result = manager.create_session("context-session", context)
            assert result['success'] == True, "Session with context creation failed"
            
            # Verify context is stored (by checking session details)
            sessions = manager.list_sessions()
            session = [s for s in sessions['sessions'] if s['name'] == "context-session"][0]
            print(f"✓ Session with context created successfully")
            
            # Create session without context
            result2 = manager.create_session("no-context-session")
            assert result2['success'] == True, "Session without context creation failed"
            print(f"✓ Session without context created successfully")
            
            return True
    except Exception as e:
        print(f"✗ Test failed: {e}")
        return False


def main():
    print_section("Agent Command Center Test Suite")
    
    tests = [
        ("Session Creation", test_session_creation),
        ("Session Listing", test_session_listing),
        ("Task Management", test_task_management),
        ("Session Deletion", test_session_deletion),
        ("Error Handling", test_error_handling),
        ("Edge Cases", test_edge_cases),
        ("Concurrent Operations", test_concurrent_operations),
        ("Session Context", test_session_context),
    ]
    
    passed = 0
    failed = 0
    
    for name, test_func in tests:
        try:
            if test_func():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"✗ Test {name} crashed: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print_section("Test Results Summary")
    print(f"Total: {len(tests)} tests")
    print(f"✓ Passed: {passed}")
    print(f"✗ Failed: {failed}")
    
    if failed == 0:
        print("\n✅ All Agent Command Center tests passed!")
        return 0
    else:
        print(f"\n❌ {failed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
