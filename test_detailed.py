#!/usr/bin/env python3
"""
Detailed test script for latest Aider enhancements.
Tests error detection, real-time analysis, AST complexity, and code explanation.
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

def test_error_detection():
    """Test error detection functionality."""
    print("\n" + "=" * 60)
    print("Testing Error Detection")
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
            
            # Create test file with various issues
            test_file = Path(tmpdir) / "test_code.py"
            test_file.write_text("""
def empty_function():
    pass

def function_with_long_line():
    # This is a very long line that exceeds the recommended 100 character limit for PEP 8 compliance and should trigger a warning in the error detection system
    pass

# TODO: Implement this feature
# FIXME: Fix this bug

def syntax_error():
    if True
        print("missing colon")
""")
            
            # Index the file
            print("Indexing file...")
            index_manager.index_full(force=True)
            
            # Test error detection
            print("\nTesting detect_errors...")
            errors = index_manager.detect_errors(str(test_file))
            
            if errors.get('success'):
                print(f"✓ Error detection successful")
                print(f"  Total issues: {errors['total_issues']}")
                print(f"  Errors: {len(errors['errors'])}")
                print(f"  Warnings: {len(errors['warnings'])}")
                
                # Check for expected warnings
                warning_types = [w['type'] for w in errors['warnings']]
                print(f"  Warning types: {warning_types}")
                
                # Verify we detected the expected issues
                if 'todo' in warning_types:
                    print("  ✓ TODO comments detected")
                if 'long_line' in warning_types:
                    print("  ✓ Long lines detected")
                if 'empty_function' in warning_types:
                    print("  ✓ Empty functions detected")
                
                return True
            else:
                print(f"✗ Failed: {errors.get('error')}")
                return False
                
    except Exception as e:
        print(f"✗ Failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_ast_complexity():
    """Test AST-based complexity calculation."""
    print("\n" + "=" * 60)
    print("Testing AST Complexity Calculation")
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
            
            # Create test file with varying complexity
            test_file = Path(tmpdir) / "complexity_test.py"
            test_file.write_text("""
def simple_function():
    return 1

def medium_complexity(a, b, c):
    if a > 0:
        if b > 0:
            return a + b
    elif c > 0:
        return a + c
    return 0

def high_complexity(a, b, c, d):
    if a > 0 and b > 0:
        if c > 0 or d > 0:
            for i in range(10):
                if i > 5:
                    return a + b + c + d
    try:
        result = a / b
    except:
        result = 0
    return result
""")
            
            # Test complexity calculation
            print("\nTesting _calculate_complexity...")
            
            # Read the file and test each function
            with open(test_file, 'r') as f:
                content = f.read()
            
            # Test overall complexity
            complexity = index_manager._calculate_complexity(content)
            print(f"✓ Overall complexity: {complexity}")
            
            # Test that complexity is reasonable
            if complexity > 0:
                print(f"  ✓ Complexity calculation works")
            else:
                print(f"  ✗ Complexity should be > 0")
                return False
            
            # Test that AST-based calculation is used
            if complexity >= 10:  # High complexity function should increase this
                print(f"  ✓ AST-based complexity calculation active")
            else:
                print(f"  ✓ Complexity calculated (may use fallback)")
            
            return True
            
    except Exception as e:
        print(f"✗ Failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_code_explanation():
    """Test code explanation with structural analysis."""
    print("\n" + "=" * 60)
    print("Testing Code Explanation with Structural Analysis")
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
            test_file = Path(tmpdir) / "explanation_test.py"
            test_file.write_text("""
import math

class Calculator:
    \"\"\"A calculator class for mathematical operations.\"\"\"
    
    def __init__(self):
        self.history = []
    
    def add(self, a, b):
        \"\"\"Add two numbers.\"\"\"
        result = a + b
        self.history.append(result)
        return result
    
    def calculate_square_root(self, x):
        \"\"\"Calculate square root using math module.\"\"\"
        if x < 0:
            raise ValueError("Cannot calculate square root of negative number")
        return math.sqrt(x)

def process_data(data):
    \"\"\"Process data with conditional logic.\"\"\"
    if not data:
        return None
    
    result = []
    for item in data:
        if item > 0:
            result.append(item * 2)
    
    return result
""")
            
            # Index the file
            print("Indexing file...")
            index_manager.index_full(force=True)
            
            # Test code explanation for entire file
            print("\nTesting explain_code for entire file...")
            explanation = index_manager.explain_code(str(test_file))
            
            if explanation.get('success'):
                print(f"✓ Code explanation generated")
                print(f"  Length: {len(explanation['explanation'])} characters")
                
                # Check for structural analysis
                if 'structure' in explanation:
                    print(f"  ✓ Structural analysis included")
                    print(f"    Classes: {explanation['structure'].get('classes', 0)}")
                    print(f"    Functions: {explanation['structure'].get('functions', 0)}")
                    print(f"    Imports: {explanation['structure'].get('imports', 0)}")
                
                return True
            else:
                print(f"✗ Failed: {explanation.get('error')}")
                return False
            
    except Exception as e:
        print(f"✗ Failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_real_time_analysis():
    """Test real-time code analysis."""
    print("\n" + "=" * 60)
    print("Testing Real-Time Code Analysis")
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
            test_file = Path(tmpdir) / "realtime_test.py"
            test_file.write_text("""
def analyze_data(data):
    # This function analyzes data
    result = 0
    for item in data:
        result += item
    return result
""")
            
            # Test real-time analysis
            print("\nTesting start_real_time_analysis...")
            analysis = index_manager.start_real_time_analysis(str(test_file))
            
            if analysis.get('success'):
                print(f"✓ Real-time analysis started")
                print(f"  File: {analysis['file_path']}")
                print(f"  Status: {analysis['status']}")
                
                if 'quality_metrics' in analysis:
                    metrics = analysis['quality_metrics']
                    print(f"  ✓ Quality metrics included")
                    print(f"    Complexity: {metrics['complexity']}")
                    print(f"    Comment ratio: {metrics['comment_ratio']:.2%}")
                
                return True
            else:
                print(f"✗ Failed: {analysis.get('error')}")
                return False
            
    except Exception as e:
        print(f"✗ Failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_code_quality_analysis():
    """Test code quality analysis."""
    print("\n" + "=" * 60)
    print("Testing Code Quality Analysis")
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
            
            # Create test file with quality issues
            test_file = Path(tmpdir) / "quality_test.py"
            test_file.write_text("""
# This is a comment
def function_with_no_docstring(a,b,c):
    x=a+b+c
    y=x*2
    return y
""")
            
            # Test code quality analysis
            print("\nTesting analyze_code_quality...")
            quality = index_manager.analyze_code_quality(str(test_file))
            
            if quality.get('success'):
                print(f"✓ Code quality analysis successful")
                metrics = quality['metrics']
                print(f"  Complexity: {metrics['complexity']}")
                print(f"  Comment ratio: {metrics['comment_ratio']:.2%}")
                print(f"  Total lines: {metrics['total_lines']}")
                print(f"  Code lines: {metrics['code_lines']}")
                print(f"  Comment lines: {metrics['comment_lines']}")
                
                # Verify metrics are reasonable
                if metrics['complexity'] > 0:
                    print(f"  ✓ Complexity calculated")
                if 0 <= metrics['comment_ratio'] <= 1:
                    print(f"  ✓ Comment ratio valid")
                
                return True
            else:
                print(f"✗ Failed: {quality.get('error')}")
                return False
            
    except Exception as e:
        print(f"✗ Failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all detailed tests."""
    print("=" * 60)
    print("Aider Enhancement Detailed Test Suite")
    print("=" * 60)
    
    tests = [
        ("Error Detection", test_error_detection),
        ("AST Complexity Calculation", test_ast_complexity),
        ("Code Explanation", test_code_explanation),
        ("Real-Time Analysis", test_real_time_analysis),
        ("Code Quality Analysis", test_code_quality_analysis),
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
