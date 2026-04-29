"""
Unit tests for code quality gates module.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from aider.code_quality_gates import (
    CodeDuplicationRule,
    CodeLengthRule,
    CodeQualityGates,
    CyclomaticComplexityRule,
    QualityGate,
    QualityGateResult,
    QualityGateStatus,
    QualityIssue,
    QualityRule,
    QualitySeverity,
    get_code_quality_gates,
)


class TestQualityIssue(unittest.TestCase):
    """Test quality issue dataclass."""

    def test_quality_issue_creation(self):
        """Test creating a quality issue."""
        issue = QualityIssue(
            rule_id="test_rule",
            severity=QualitySeverity.HIGH,
            message="Test issue",
            file_path="test.py",
            line_number=10,
        )
        
        self.assertEqual(issue.rule_id, "test_rule")
        self.assertEqual(issue.severity, QualitySeverity.HIGH)


class TestQualityGateResult(unittest.TestCase):
    """Test quality gate result dataclass."""

    def test_quality_gate_result_creation(self):
        """Test creating a quality gate result."""
        result = QualityGateResult(
            gate_name="test_gate",
            status=QualityGateStatus.PASSED,
        )
        
        self.assertEqual(result.gate_name, "test_gate")
        self.assertEqual(result.status, QualityGateStatus.PASSED)


class TestCyclomaticComplexityRule(unittest.TestCase):
    """Test cyclomatic complexity rule."""

    def setUp(self):
        """Set up test fixtures."""
        self.rule = CyclomaticComplexityRule(max_complexity=5)
    
    def test_check_simple_function(self):
        """Test checking a simple function."""
        code = """
def simple_function():
    return 42
"""
        with TemporaryDirectory() as temp_dir:
            test_file = Path(temp_dir) / "test.py"
            test_file.write_text(code)
            
            issues = self.rule.check(test_file)
            
            # Simple function should have low complexity
            self.assertEqual(len(issues), 0)
    
    def test_check_complex_function(self):
        """Test checking a complex function."""
        code = """
def complex_function(x):
    if x > 0:
        if x > 10:
            if x > 20:
                if x > 30:
                    if x > 40:
                        return x
    return 0
"""
        with TemporaryDirectory() as temp_dir:
            test_file = Path(temp_dir) / "test.py"
            test_file.write_text(code)
            
            issues = self.rule.check(test_file)
            
            # Complex function should trigger complexity issue
            self.assertGreater(len(issues), 0)


class TestCodeDuplicationRule(unittest.TestCase):
    """Test code duplication rule."""

    def setUp(self):
        """Set up test fixtures."""
        self.rule = CodeDuplicationRule(min_duplicate_lines=3)
    
    def test_check_no_duplication(self):
        """Test checking code with no duplication."""
        code = """
def function1():
    return 1

def function2():
    return 2
"""
        with TemporaryDirectory() as temp_dir:
            test_file = Path(temp_dir) / "test.py"
            test_file.write_text(code)
            
            issues = self.rule.check(test_file)
            
            self.assertEqual(len(issues), 0)
    
    def test_check_with_duplication(self):
        """Test checking code with duplication."""
        code = """
x = 1
x = 1
x = 1
x = 1
x = 1
"""
        with TemporaryDirectory() as temp_dir:
            test_file = Path(temp_dir) / "test.py"
            test_file.write_text(code)
            
            issues = self.rule.check(test_file)
            
            # Should detect duplication
            self.assertGreater(len(issues), 0)


class TestCodeLengthRule(unittest.TestCase):
    """Test code length rule."""

    def setUp(self):
        """Set up test fixtures."""
        self.rule = CodeLengthRule(max_lines=10)
    
    def test_check_short_file(self):
        """Test checking a short file."""
        code = "x = 1\n" * 5
        
        with TemporaryDirectory() as temp_dir:
            test_file = Path(temp_dir) / "test.py"
            test_file.write_text(code)
            
            issues = self.rule.check(test_file)
            
            self.assertEqual(len(issues), 0)
    
    def test_check_long_file(self):
        """Test checking a long file."""
        code = "x = 1\n" * 20
        
        with TemporaryDirectory() as temp_dir:
            test_file = Path(temp_dir) / "test.py"
            test_file.write_text(code)
            
            issues = self.rule.check(test_file)
            
            # Should detect long file
            self.assertGreater(len(issues), 0)


class TestQualityGate(unittest.TestCase):
    """Test quality gate functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.gate = QualityGate("test_gate")
    
    def test_add_rule(self):
        """Test adding a rule to the gate."""
        rule = CyclomaticComplexityRule()
        self.gate.add_rule(rule)
        
        self.assertEqual(len(self.gate.rules), 1)
    
    def test_check_file(self):
        """Test checking a file."""
        self.gate.add_rule(CodeLengthRule(max_lines=10))
        
        code = "x = 1\n" * 5
        
        with TemporaryDirectory() as temp_dir:
            test_file = Path(temp_dir) / "test.py"
            test_file.write_text(code)
            
            issues = self.gate.check_file(test_file)
            
            self.assertIsInstance(issues, list)


class TestCodeQualityGates(unittest.TestCase):
    """Test code quality gates manager."""

    def setUp(self):
        """Set up test fixtures."""
        self.manager = CodeQualityGates()
    
    def test_register_gate(self):
        """Test registering a quality gate."""
        gate = QualityGate("custom_gate")
        self.manager.register_gate(gate)
        
        retrieved = self.manager.get_gate("custom_gate")
        self.assertIsNotNone(retrieved)
    
    def test_get_default_gates(self):
        """Test that default gates are registered."""
        gates = self.manager.gates
        
        self.assertIn("complexity", gates)
        self.assertIn("duplication", gates)
        self.assertIn("length", gates)
    
    def test_run_all_gates(self):
        """Test running all quality gates."""
        with TemporaryDirectory() as temp_dir:
            # Create a test Python file
            test_file = Path(temp_dir) / "test.py"
            test_file.write_text("x = 1\n")
            
            results = self.manager.run_all_gates(Path(temp_dir))
            
            self.assertIn("complexity", results)
            self.assertIn("duplication", results)
            self.assertIn("length", results)
    
    def test_generate_report(self):
        """Test generating quality report."""
        with TemporaryDirectory() as temp_dir:
            # Create a test Python file
            test_file = Path(temp_dir) / "test.py"
            test_file.write_text("x = 1\n")
            
            results = self.manager.run_all_gates(Path(temp_dir))
            report = self.manager.generate_report(results)
            
            self.assertIn("timestamp", report)
            self.assertIn("overall_status", report)
            self.assertIn("total_issues", report)


class TestGlobalCodeQualityGates(unittest.TestCase):
    """Test global code quality gates instance."""

    def test_get_code_quality_gates(self):
        """Test getting global code quality gates."""
        manager = get_code_quality_gates()
        self.assertIsNotNone(manager)
        
        # Should return same instance
        manager2 = get_code_quality_gates()
        self.assertIs(manager, manager2)


if __name__ == "__main__":
    unittest.main()
