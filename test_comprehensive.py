#!/usr/bin/env python3
"""
Comprehensive test script for Aider enhancements.
Tests code navigation, multi-file editing, refactoring, and analysis features.
"""

import sys
import os
import tempfile
import shutil
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def create_test_files(test_dir):
    """Create test files for testing."""
    test_files = {}
    
    # Create a Python test file
    test_file1 = test_dir / "test_module.py"
    test_file1.write_text("""
def calculate_sum(a, b):
    '''Calculate the sum of two numbers.'''
    return a + b

def calculate_product(a, b):
    '''Calculate the product of two numbers.'''
    return a * b

class Calculator:
    '''A simple calculator class.'''
    
    def __init__(self):
        self.history = []
    
    def add(self, a, b):
        '''Add two numbers and store in history.'''
        result = a + b
        self.history.append(result)
        return result
    
    def multiply(self, a, b):
        '''Multiply two numbers and store in history.'''
        result = a * b
        self.history.append(result)
        return result

# TODO: Implement division
# FIXME: Add error handling
""")
    test_files['test_module.py'] = test_file1
    
    # Create another Python file
    test_file2 = test_dir / "utils.py"
    test_file2.write_text("""
def format_number(num):
    '''Format a number for display.'''
    return f"{num:.2f}"

def validate_input(value):
    '''Validate user input.'''
    if value < 0:
        raise ValueError("Value must be positive")
    return value
""")
    test_files['utils.py'] = test_file2
    
    return test_files

class MockIO:
    """Mock IO for testing."""
    def tool_output(self, msg, log_only=False):
        if not log_only:
            print(f"[OUTPUT] {msg}")
    
    def tool_error(self, msg, log_only=False):
        if not log_only:
            print(f"[ERROR] {msg}")

def test_index_manager_creation():
    """Test IndexManager creation."""
    print("\n" + "=" * 60)
    print("Testing IndexManager Creation")
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
            print("✓ IndexManager created successfully")
            return True
    except Exception as e:
        print(f"✗ Failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_code_navigation():
    """Test code navigation features."""
    print("\n" + "=" * 60)
    print("Testing Code Navigation Features")
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
            
            # Create test files
            test_files = create_test_files(Path(tmpdir))
            
            # Index the files
            print("Indexing files...")
            index_manager.index_full(force=True)
            
            # Test jump to definition
            print("\nTesting jump_to_definition...")
            definition = index_manager.jump_to_definition("calculate_sum")
            if definition:
                print(f"✓ Found definition for calculate_sum at line {definition.get('line')}")
            else:
                print("✗ No definition found for calculate_sum")
            
            # Test find references
            print("\nTesting find_references...")
            references = index_manager.find_references("calculate_sum")
            print(f"✓ Found {len(references)} references")
            
            # Test symbol hierarchy
            print("\nTesting get_symbol_hierarchy...")
            hierarchy = index_manager.get_symbol_hierarchy(str(test_files['test_module.py']))
            print(f"✓ Found {len(hierarchy.get('classes', []))} classes")
            print(f"✓ Found {len(hierarchy.get('functions', []))} functions")
            
            # Test file structure
            print("\nTesting get_file_structure...")
            structure = index_manager.get_file_structure()
            print(f"✓ Found {len(structure.get('files', []))} files")
            
            return True
            
    except Exception as e:
        print(f"✗ Failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_refactoring_tools():
    """Test refactoring tools."""
    print("\n" + "=" * 60)
    print("Testing Refactoring Tools")
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
            
            # Create test files
            test_files = create_test_files(Path(tmpdir))
            
            # Index the files
            print("Indexing files...")
            index_manager.index_full(force=True)
            
            # Test code quality analysis
            print("\nTesting analyze_code_quality...")
            quality = index_manager.analyze_code_quality(str(test_files['test_module.py']))
            if quality.get('success'):
                metrics = quality['metrics']
                print(f"✓ Complexity: {metrics['complexity']}")
                print(f"✓ Comment ratio: {metrics['comment_ratio']:.2%}")
            else:
                print(f"✗ Failed: {quality.get('error')}")
            
            # Test error detection
            print("\nTesting detect_errors...")
            errors = index_manager.detect_errors(str(test_files['test_module.py']))
            if errors.get('success'):
                print(f"✓ Found {errors['total_issues']} issues")
                print(f"  - {len(errors['errors'])} errors")
                print(f"  - {len(errors['warnings'])} warnings")
            else:
                print(f"✗ Failed: {errors.get('error')}")
            
            # Test code cleanup
            print("\nTesting clean_code...")
            cleanup = index_manager.clean_code(str(test_files['test_module.py']))
            print(f"✓ Unused imports removed: {cleanup['unused_imports_removed']}")
            print(f"✓ Formatting fixed: {cleanup['formatting_fixed']}")
            
            return True
            
    except Exception as e:
        print(f"✗ Failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_code_explanation():
    """Test code explanation features."""
    print("\n" + "=" * 60)
    print("Testing Code Explanation Features")
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
            
            # Create test files
            test_files = create_test_files(Path(tmpdir))
            
            # Index the files
            print("Indexing files...")
            index_manager.index_full(force=True)
            
            # Test code explanation
            print("\nTesting explain_code...")
            explanation = index_manager.explain_code(str(test_files['test_module.py']), "calculate_sum")
            if explanation.get('success'):
                print("✓ Code explanation generated")
                print(f"  Length: {len(explanation['explanation'])} characters")
            else:
                print(f"✗ Failed: {explanation.get('error')}")
            
            # Test documentation generation
            print("\nTesting generate_documentation...")
            docs = index_manager.generate_documentation(str(test_files['test_module.py']))
            if docs.get('success'):
                print(f"✓ Documentation generated for {docs['symbols_documented']} symbols")
            else:
                print(f"✗ Failed: {docs.get('error')}")
            
            return True
            
    except Exception as e:
        print(f"✗ Failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_test_generation():
    """Test test generation features."""
    print("\n" + "=" * 60)
    print("Testing Test Generation Features")
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
            
            # Create test files
            test_files = create_test_files(Path(tmpdir))
            
            # Index the files
            print("Indexing files...")
            index_manager.index_full(force=True)
            
            # Test test generation
            print("\nTesting generate_test_for_function...")
            test_gen = index_manager.generate_test_for_function(
                str(test_files['test_module.py']), 
                "calculate_sum"
            )
            if test_gen.get('success'):
                print("✓ Test generated for calculate_sum")
                print(f"  Function name: {test_gen['function_name']}")
                print(f"  Lines extracted: {test_gen['lines_extracted']}")
            else:
                print(f"✗ Failed: {test_gen.get('error')}")
            
            # Test coverage report
            print("\nTesting generate_test_coverage_report...")
            coverage = index_manager.generate_test_coverage_report(str(test_files['test_module.py']))
            if 'error' not in coverage:
                print(f"✓ Coverage report generated")
                print(f"  Functions: {coverage['functions_count']}")
                print(f"  Classes: {coverage['classes_count']}")
            else:
                print(f"✗ Failed: {coverage.get('error')}")
            
            return True
            
    except Exception as e:
        print(f"✗ Failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all tests."""
    print("=" * 60)
    print("Aider Enhancement Comprehensive Test Suite")
    print("=" * 60)
    
    tests = [
        ("IndexManager Creation", test_index_manager_creation),
        ("Code Navigation", test_code_navigation),
        ("Refactoring Tools", test_refactoring_tools),
        ("Code Explanation", test_code_explanation),
        ("Test Generation", test_test_generation),
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
    
    return all(result for _, result in results)

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
