#!/usr/bin/env python3
"""
Workspace Management Test Suite
Tests for workspace (Spaces) management functionality
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from aider.index_manager import IndexManager
from datetime import datetime
import tempfile
import uuid


def print_section(title):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def test_workspace_creation():
    print_section("Testing Workspace Creation")
    
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = IndexManager(tmpdir)
            
            # Test basic workspace creation
            result = manager.create_workspace("test-workspace")
            assert result['success'] == True, "Workspace creation failed"
            assert 'workspace_id' in result, "Workspace ID not in result"
            assert result['workspace_name'] == "test-workspace", "Workspace name mismatch"
            print(f"✓ Basic workspace creation successful")
            print(f"  Workspace ID: {result['workspace_id']}")
            
            # Test workspace with description
            result2 = manager.create_workspace("workspace-with-desc", "Test description")
            assert result2['success'] == True, "Workspace with description creation failed"
            print(f"✓ Workspace with description creation successful")
            
            # Test workspace with context
            result3 = manager.create_workspace("workspace-with-context", context={"project": "test"})
            assert result3['success'] == True, "Workspace with context creation failed"
            print(f"✓ Workspace with context creation successful")
            
            # Verify workspaces are stored
            workspaces = manager.list_workspaces()
            assert workspaces['success'] == True, "List workspaces failed"
            assert workspaces['count'] == 3, f"Expected 3 workspaces, got {workspaces['count']}"
            print(f"✓ Workspaces stored correctly (count: {workspaces['count']})")
            
            return True
    except Exception as e:
        print(f"✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_workspace_listing():
    print_section("Testing Workspace Listing")
    
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = IndexManager(tmpdir)
            
            # Create multiple workspaces
            manager.create_workspace("workspace-1")
            manager.create_workspace("workspace-2", "Description 2")
            manager.create_workspace("workspace-3", "Description 3")
            
            # List workspaces
            result = manager.list_workspaces()
            assert result['success'] == True, "List workspaces failed"
            assert result['count'] == 3, f"Expected 3 workspaces, got {result['count']}"
            
            print(f"✓ Workspace listing successful (count: {result['count']})")
            
            # Verify workspace structure
            for workspace in result['workspaces']:
                assert 'id' in workspace, "Workspace missing ID"
                assert 'name' in workspace, "Workspace missing name"
                assert 'status' in workspace, "Workspace missing status"
                assert 'created_at' in workspace, "Workspace missing created_at"
                assert 'session_count' in workspace, "Workspace missing session_count"
            
            print(f"✓ Workspace structure validation passed")
            
            return True
    except Exception as e:
        print(f"✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_session_workspace_linking():
    print_section("Testing Session-Workspace Linking")
    
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = IndexManager(tmpdir)
            
            # Create workspace
            workspace_result = manager.create_workspace("test-workspace")
            workspace_id = workspace_result['workspace_id']
            print(f"  Created workspace: {workspace_id}")
            
            # Create sessions
            session1 = manager.create_session("session-1")
            session2 = manager.create_session("session-2")
            session3 = manager.create_session("session-3")
            print(f"  Created 3 sessions")
            
            # Add sessions to workspace
            result1 = manager.add_session_to_workspace(workspace_id, session1['session_id'])
            assert result1['success'] == True, "Add session 1 failed"
            print(f"✓ Session 1 added to workspace")
            
            result2 = manager.add_session_to_workspace(workspace_id, session2['session_id'])
            assert result2['success'] == True, "Add session 2 failed"
            print(f"✓ Session 2 added to workspace")
            
            result3 = manager.add_session_to_workspace(workspace_id, session3['session_id'])
            assert result3['success'] == True, "Add session 3 failed"
            print(f"✓ Session 3 added to workspace")
            
            # Get workspace sessions
            sessions_result = manager.get_workspace_sessions(workspace_id)
            assert sessions_result['success'] == True, "Get workspace sessions failed"
            assert sessions_result['count'] == 3, f"Expected 3 sessions, got {sessions_result['count']}"
            print(f"✓ Workspace session retrieval successful (count: {sessions_result['count']})")
            
            # Verify workspace session count
            workspaces = manager.list_workspaces()
            workspace = [w for w in workspaces['workspaces'] if w['id'] == workspace_id][0]
            assert workspace['session_count'] == 3, f"Expected 3 sessions in workspace, got {workspace['session_count']}"
            print(f"✓ Workspace session count verification passed")
            
            return True
    except Exception as e:
        print(f"✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_session_removal_from_workspace():
    print_section("Testing Session Removal from Workspace")
    
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = IndexManager(tmpdir)
            
            # Create workspace and sessions
            workspace = manager.create_workspace("test-workspace")
            session1 = manager.create_session("session-1")
            session2 = manager.create_session("session-2")
            
            # Add sessions to workspace
            manager.add_session_to_workspace(workspace['workspace_id'], session1['session_id'])
            manager.add_session_to_workspace(workspace['workspace_id'], session2['session_id'])
            
            # Verify sessions are in workspace
            sessions_before = manager.get_workspace_sessions(workspace['workspace_id'])
            assert sessions_before['count'] == 2, f"Expected 2 sessions before removal"
            print(f"✓ Sessions before removal: {sessions_before['count']}")
            
            # Remove one session
            result = manager.remove_session_from_workspace(workspace['workspace_id'], session1['session_id'])
            assert result['success'] == True, "Session removal failed"
            print(f"✓ Session removed successfully")
            
            # Verify removal
            sessions_after = manager.get_workspace_sessions(workspace['workspace_id'])
            assert sessions_after['count'] == 1, f"Expected 1 session after removal"
            assert sessions_after['sessions'][0]['id'] == session2['session_id'], "Wrong session removed"
            print(f"✓ Session removal verified (count: {sessions_after['count']})")
            
            return True
    except Exception as e:
        print(f"✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_workspace_deletion():
    print_section("Testing Workspace Deletion")
    
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = IndexManager(tmpdir)
            
            # Create workspaces
            workspace1 = manager.create_workspace("workspace-to-delete")
            workspace2 = manager.create_workspace("workspace-to-keep")
            
            # Add sessions to workspace1
            session1 = manager.create_session("session-1")
            session2 = manager.create_session("session-2")
            manager.add_session_to_workspace(workspace1['workspace_id'], session1['session_id'])
            manager.add_session_to_workspace(workspace1['workspace_id'], session2['session_id'])
            
            # Verify workspaces exist
            before_delete = manager.list_workspaces()
            assert before_delete['count'] == 2, "Expected 2 workspaces before deletion"
            print(f"✓ Workspaces before deletion: {before_delete['count']}")
            
            # Delete workspace
            delete_result = manager.delete_workspace(workspace1['workspace_id'])
            assert delete_result['success'] == True, "Workspace deletion failed"
            print(f"✓ Workspace deleted successfully")
            
            # Verify deletion
            after_delete = manager.list_workspaces()
            assert after_delete['count'] == 1, f"Expected 1 workspace after deletion, got {after_delete['count']}"
            assert after_delete['workspaces'][0]['id'] == workspace2['workspace_id'], "Wrong workspace deleted"
            print(f"✓ Workspace deletion verified (count: {after_delete['count']})")
            
            # Verify sessions still exist (workspace deletion should not delete sessions)
            sessions = manager.list_sessions()
            assert sessions['count'] == 2, f"Expected 2 sessions to still exist"
            print(f"✓ Sessions persist after workspace deletion (count: {sessions['count']})")
            
            return True
    except Exception as e:
        print(f"✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_error_handling():
    print_section("Testing Error Handling")
    
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = IndexManager(tmpdir)
            
            # Test adding session to non-existent workspace
            session = manager.create_session("test-session")
            result = manager.add_session_to_workspace("non-existent-workspace", session['session_id'])
            assert result['success'] == False, "Should fail for non-existent workspace"
            assert 'error' in result, "Error message missing"
            print(f"✓ Non-existent workspace error handling passed")
            
            # Test adding non-existent session to workspace
            workspace = manager.create_workspace("test-workspace")
            result = manager.add_session_to_workspace(workspace['workspace_id'], "non-existent-session")
            assert result['success'] == False, "Should fail for non-existent session"
            print(f"✓ Non-existent session error handling passed")
            
            # Test adding same session twice
            result1 = manager.add_session_to_workspace(workspace['workspace_id'], session['session_id'])
            assert result1['success'] == True, "First add should succeed"
            result2 = manager.add_session_to_workspace(workspace['workspace_id'], session['session_id'])
            assert result2['success'] == False, "Second add should fail"
            print(f"✓ Duplicate session addition error handling passed")
            
            # Test removing session from non-existent workspace
            result = manager.remove_session_from_workspace("non-existent-workspace", session['session_id'])
            assert result['success'] == False, "Should fail for non-existent workspace"
            print(f"✓ Non-existent workspace removal error handling passed")
            
            # Test removing non-existent session from workspace
            result = manager.remove_session_from_workspace(workspace['workspace_id'], "non-existent-session")
            assert result['success'] == False, "Should fail for non-existent session"
            print(f"✓ Non-existent session removal error handling passed")
            
            # Test getting sessions from non-existent workspace
            result = manager.get_workspace_sessions("non-existent-workspace")
            assert result['success'] == False, "Should fail for non-existent workspace"
            print(f"✓ Non-existent workspace sessions retrieval error handling passed")
            
            # Test deleting non-existent workspace
            result = manager.delete_workspace("non-existent-workspace")
            assert result['success'] == False, "Should fail for non-existent workspace"
            print(f"✓ Non-existent workspace deletion error handling passed")
            
            return True
    except Exception as e:
        print(f"✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_edge_cases():
    print_section("Testing Edge Cases")
    
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = IndexManager(tmpdir)
            
            # Test empty workspace name
            result = manager.create_workspace("")
            assert result['success'] == True, "Empty workspace name should be allowed"
            print(f"✓ Empty workspace name handling passed")
            
            # Test very long workspace name
            long_name = "a" * 1000
            result = manager.create_workspace(long_name)
            assert result['success'] == True, "Long workspace name should be allowed"
            print(f"✓ Long workspace name handling passed")
            
            # Test special characters in workspace name
            special_name = "test-workspace-with_special.chars!"
            result = manager.create_workspace(special_name)
            assert result['success'] == True, "Special characters in name should be allowed"
            print(f"✓ Special characters in workspace name handling passed")
            
            # Test very long description
            long_desc = "a" * 5000
            result = manager.create_workspace("test-workspace", long_desc)
            assert result['success'] == True, "Long description should be allowed"
            print(f"✓ Long description handling passed")
            
            # Test workspace with complex context
            complex_context = {
                "project": "test",
                "files": ["file1.py", "file2.py", "file3.py"],
                "settings": {"key1": "value1", "key2": "value2"},
                "metadata": {"nested": {"data": [1, 2, 3]}}
            }
            result = manager.create_workspace("test-workspace", context=complex_context)
            assert result['success'] == True, "Complex context should be allowed"
            print(f"✓ Complex context handling passed")
            
            # Test listing workspaces when none exist (use same manager, clear workspaces)
            # Clear all workspaces first
            all_workspaces = manager.list_workspaces()
            for w in all_workspaces['workspaces']:
                manager.delete_workspace(w['id'])
            
            result = manager.list_workspaces()
            assert result['success'] == True, "Listing empty workspaces should succeed"
            assert result['count'] == 0, "Empty workspaces should have count 0"
            print(f"✓ Empty workspace list handling passed")
            
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
            
            # Create multiple workspaces rapidly
            workspace_ids = []
            for i in range(10):
                result = manager.create_workspace(f"concurrent-workspace-{i}")
                assert result['success'] == True, f"Workspace {i} creation failed"
                workspace_ids.append(result['workspace_id'])
            
            print(f"✓ Rapid workspace creation (10 workspaces)")
            
            # Create sessions and add to workspaces
            for i, workspace_id in enumerate(workspace_ids):
                for j in range(5):
                    session = manager.create_session(f"session-{i}-{j}")
                    result = manager.add_session_to_workspace(workspace_id, session['session_id'])
                    assert result['success'] == True, f"Session addition failed for workspace {workspace_id}"
            
            print(f"✓ Rapid session addition (50 sessions across 10 workspaces)")
            
            # Verify all workspaces and sessions
            workspaces = manager.list_workspaces()
            assert workspaces['count'] == 10, f"Expected 10 workspaces, got {workspaces['count']}"
            
            total_sessions = 0
            for workspace in workspaces['workspaces']:
                total_sessions += workspace['session_count']
            
            assert total_sessions == 50, f"Expected 50 sessions, got {total_sessions}"
            print(f"✓ Concurrent operations verification passed (10 workspaces, 50 sessions)")
            
            return True
    except Exception as e:
        print(f"✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_workspace_session_integration():
    print_section("Testing Workspace-Session Integration")
    
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = IndexManager(tmpdir)
            
            # Create workspace
            workspace = manager.create_workspace("project-workspace", "Main project workspace")
            workspace_id = workspace['workspace_id']
            
            # Create sessions with tasks
            session1 = manager.create_session("dev-session")
            session2 = manager.create_session("test-session")
            
            # Add tasks to sessions
            manager.add_task_to_session(session1['session_id'], "Implement feature X", "feature")
            manager.add_task_to_session(session1['session_id'], "Fix bug Y", "bugfix")
            manager.add_task_to_session(session2['session_id'], "Write tests", "testing")
            
            # Add sessions to workspace
            manager.add_session_to_workspace(workspace_id, session1['session_id'])
            manager.add_session_to_workspace(workspace_id, session2['session_id'])
            
            # Get workspace sessions
            result = manager.get_workspace_sessions(workspace_id)
            assert result['success'] == True, "Get workspace sessions failed"
            assert result['count'] == 2, f"Expected 2 sessions"
            
            # Verify task counts in workspace sessions
            total_tasks = sum(s['task_count'] for s in result['sessions'])
            assert total_tasks == 3, f"Expected 3 tasks total, got {total_tasks}"
            print(f"✓ Workspace-session integration successful (2 sessions, 3 tasks)")
            
            # Update task status
            session1_tasks = manager.get_session_tasks(session1['session_id'])
            manager.update_task_status(session1['session_id'], session1_tasks['tasks'][0]['id'], "completed")
            
            # Verify task status updated
            updated_tasks = manager.get_session_tasks(session1['session_id'])
            completed_count = sum(1 for t in updated_tasks['tasks'] if t['status'] == 'completed')
            assert completed_count == 1, f"Expected 1 completed task"
            print(f"✓ Task status update successful in workspace session")
            
            return True
    except Exception as e:
        print(f"✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    print_section("Workspace Management Test Suite")
    
    tests = [
        ("Workspace Creation", test_workspace_creation),
        ("Workspace Listing", test_workspace_listing),
        ("Session-Workspace Linking", test_session_workspace_linking),
        ("Session Removal from Workspace", test_session_removal_from_workspace),
        ("Workspace Deletion", test_workspace_deletion),
        ("Error Handling", test_error_handling),
        ("Edge Cases", test_edge_cases),
        ("Concurrent Operations", test_concurrent_operations),
        ("Workspace-Session Integration", test_workspace_session_integration),
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
        print("\n✅ All Workspace Management tests passed!")
        return 0
    else:
        print(f"\n❌ {failed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
