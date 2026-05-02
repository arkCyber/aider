#!/usr/bin/env python3
"""
Test script for Phase 1 features: Code completion and Diff viewer.
Tests the newly implemented code completion and diff viewing capabilities.
"""

import sys
import os
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

class MockIO:
    """Mock IO for testing."""
    def tool_output(self, msg, log_only=False):
        if not log_only:
            print(f"[OUTPUT] {msg}")
    
    def tool_error(self, msg, log_only=False):
        if not log_only:
            print(f"[ERROR] {msg}")

def test_code_completion():
    """Test code completion functionality."""
    print("\n" + "=" * 60)
    print("Testing Code Completion")
    print("=" * 60)
    
    try:
        from aider.index_manager import IndexManager
        
        with tempfile.TemporaryDirectory() as tmpdir:
            io = MockIO()
            index_manager = IndexManager(
                root=tmpdir,
                io=io,
                enable_embeddings=False
            )
            
            # Create test file
            test_file = Path(tmpdir) / "test_completion.py"
            test_file.write_text("""
import os
import sys

def calculate_sum(a, b):
    return a + b

def calculate_product(x, y):
    return x * y

class Calculator:
    def __init__(self):
        self.value = 0
    
    def add(self, num):
        self.value += num
""")
            
            # Index the file
            print("Indexing file...")
            index_manager.index_full(force=True)
            
            # Test code completion at different positions
            print("\nTest 1: Import completion")
            completion = index_manager.get_code_completion(str(test_file), 2, 8)
            if completion['success']:
                print(f"  ✓ Completion type: {completion['completion_type']}")
                print(f"  ✓ Suggestions: {len(completion['suggestions'])}")
                if completion['suggestions']:
                    print(f"    First suggestion: {completion['suggestions'][0]['text']}")
            else:
                print(f"  ✗ Failed: {completion.get('error')}")
                return False
            
            print("\nTest 2: Function definition completion")
            completion = index_manager.get_code_completion(str(test_file), 4, 12)
            if completion['success']:
                print(f"  ✓ Completion type: {completion['completion_type']}")
                print(f"  ✓ Suggestions: {len(completion['suggestions'])}")
            else:
                print(f"  ✗ Failed: {completion.get('error')}")
                return False
            
            print("\nTest 3: General completion")
            completion = index_manager.get_code_completion(str(test_file), 7, 5)
            if completion['success']:
                print(f"  ✓ Completion type: {completion['completion_type']}")
                print(f"  ✓ Suggestions: {len(completion['suggestions'])}")
            else:
                print(f"  ✗ Failed: {completion.get('error')}")
                return False
            
            return True
            
    except Exception as e:
        print(f"✗ Failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_inline_completion():
    """Test inline code completion functionality."""
    print("\n" + "=" * 60)
    print("Testing Inline Completion")
    print("=" * 60)
    
    try:
        from aider.index_manager import IndexManager
        
        with tempfile.TemporaryDirectory() as tmpdir:
            io = MockIO()
            index_manager = IndexManager(
                root=tmpdir,
                io=io,
                enable_embeddings=False
            )
            
            # Create test file
            test_file = Path(tmpdir) / "test_inline.py"
            test_file.write_text("""
def process_data(data):
    result = []
    for item in data:
        result.append(item * 2)
    return result
""")
            
            # Index the file
            print("Indexing file...")
            index_manager.index_full(force=True)
            
            # Test inline completion
            print("\nTest: Inline completion at position")
            completion = index_manager.get_inline_completion(str(test_file), 3, 15)
            
            if completion['success']:
                print(f"  ✓ File: {completion['file_path']}")
                print(f"  ✓ Position: Line {completion['cursor_position']['line']}, Col {completion['cursor_position']['column']}")
                print(f"  ✓ Type: {completion['type']}")
                
                if completion['suggestion']:
                    print(f"  ✓ Suggestion: {completion['completion_text']}")
                    print(f"  ✓ Description: {completion['suggestion']['description']}")
                else:
                    print(f"  ✓ No suggestion available (expected for this position)")
                
                return True
            else:
                print(f"  ✗ Failed: {completion.get('error')}")
                return False
            
    except Exception as e:
        print(f"✗ Failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_diff_generation():
    """Test diff generation functionality."""
    print("\n" + "=" * 60)
    print("Testing Diff Generation")
    print("=" * 60)
    
    try:
        from aider.index_manager import IndexManager
        
        with tempfile.TemporaryDirectory() as tmpdir:
            io = MockIO()
            index_manager = IndexManager(
                root=tmpdir,
                io=io,
                enable_embeddings=False
            )
            
            old_content = """def old_function():
    return 1
"""
            
            new_content = """def new_function():
    return 2
    
def another_function():
    return 3
"""
            
            print("Generating diff...")
            diff_result = index_manager.generate_diff(old_content, new_content, "test.py")
            
            if diff_result['success']:
                print(f"  ✓ File: {diff_result['file_path']}")
                print(f"  ✓ Stats:")
                stats = diff_result['stats']
                print(f"    Old lines: {stats['old_lines']}")
                print(f"    New lines: {stats['new_lines']}")
                print(f"    Added: {stats['added']}")
                print(f"    Removed: {stats['removed']}")
                print(f"    Changed: {stats['changed']}")
                print(f"\n  ✓ Diff generated ({len(diff_result['diff'])} characters)")
                
                return True
            else:
                print(f"  ✗ Failed: {diff_result.get('error')}")
                return False
            
    except Exception as e:
        print(f"✗ Failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_completion_types():
    """Test different completion types."""
    print("\n" + "=" * 60)
    print("Testing Completion Types")
    print("=" * 60)
    
    try:
        from aider.index_manager import IndexManager
        
        with tempfile.TemporaryDirectory() as tmpdir:
            io = MockIO()
            index_manager = IndexManager(
                root=tmpdir,
                io=io,
                enable_embeddings=False
            )
            
            # Test import completion type
            print("\nTest 1: Import completion type")
            line_prefix = "import os"
            context = "import os\nimport sys"
            completion_type = index_manager._determine_completion_type(line_prefix, context)
            print(f"  ✓ Type: {completion_type}")
            assert completion_type == 'import', f"Expected 'import', got '{completion_type}'"
            
            # Test function completion type
            print("\nTest 2: Function completion type")
            line_prefix = "def test"
            context = "def test():\n    pass"
            completion_type = index_manager._determine_completion_type(line_prefix, context)
            print(f"  ✓ Type: {completion_type}")
            assert completion_type == 'function', f"Expected 'function', got '{completion_type}'"
            
            # Test variable completion type
            print("\nTest 3: Variable completion type")
            line_prefix = "result ="
            context = "result = 0"
            completion_type = index_manager._determine_completion_type(line_prefix, context)
            print(f"  ✓ Type: {completion_type}")
            assert completion_type == 'variable', f"Expected 'variable', got '{completion_type}'"
            
            # Test function call completion type
            print("\nTest 4: Function call completion type")
            line_prefix = "print("
            context = "print("
            completion_type = index_manager._determine_completion_type(line_prefix, context)
            print(f"  ✓ Type: {completion_type}")
            assert completion_type == 'function_call', f"Expected 'function_call', got '{completion_type}'"
            
            print("\n✓ All completion type tests passed")
            return True
            
    except Exception as e:
        print(f"✗ Failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all Phase 1 tests."""
    print("=" * 60)
    print("Phase 1 Features Test Suite")
    print("Testing: Code Completion, Inline Completion, Diff Viewer")
    print("=" * 60)
    
    tests = [
        ("Code Completion", test_code_completion),
        ("Inline Completion", test_inline_completion),
        ("Diff Generation", test_diff_generation),
        ("Completion Types", test_completion_types),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"✗ Test '{test_name}' crashed: {e}")
            import traceback
            traceback.print_exc()
            results.append((test_name, False))
    
    print("\n" + "=" * 60)
    print("Test Results Summary")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {test_name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n✅ All Phase 1 tests passed!")
    else:
        print(f"\n⚠️  {total - passed} test(s) failed")
    
    return all(result for _, result in results)

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
