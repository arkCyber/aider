"""
Unit tests for configuration validation module.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from aider.config_validator import (
    ConfigValidator,
    ValidationError,
    ValidationResult,
    validate_config_file,
    get_default_config,
    generate_config_template,
)


class TestValidationError(unittest.TestCase):
    """Test validation error dataclass."""

    def test_validation_error_creation(self):
        """Test creating a validation error."""
        error = ValidationError(field="test_field", message="Test error message")
        
        self.assertEqual(error.field, "test_field")
        self.assertEqual(error.message, "Test error message")
        self.assertEqual(error.severity, "error")


class TestValidationResult(unittest.TestCase):
    """Test validation result dataclass."""

    def test_validation_result_creation(self):
        """Test creating a validation result."""
        result = ValidationResult(
            is_valid=True,
            errors=[],
            warnings=[],
            validated_config={"model": "gpt-4"},
        )
        
        self.assertTrue(result.is_valid)
        self.assertEqual(len(result.errors), 0)
        self.assertEqual(result.validated_config["model"], "gpt-4")


class TestConfigValidator(unittest.TestCase):
    """Test the configuration validator."""

    def setUp(self):
        """Set up test fixtures."""
        self.validator = ConfigValidator()
    
    def test_validate_valid_config(self):
        """Test validating a valid configuration."""
        config = {
            "model": "gpt-4",
            "max_tokens": 4096,
            "temperature": 0.5,
            "timeout": 60,
        }
        
        result = self.validator.validate(config)
        
        self.assertTrue(result.is_valid)
        self.assertEqual(len(result.errors), 0)
    
    def test_validate_missing_required_field(self):
        """Test validating config with missing required field."""
        config = {"max_tokens": 4096}  # Missing required 'model' field
        
        result = self.validator.validate(config)
        
        self.assertFalse(result.is_valid)
        self.assertGreater(len(result.errors), 0)
        self.assertTrue(any("model" in error.field for error in result.errors))
    
    def test_validate_type_conversion(self):
        """Test type conversion during validation."""
        config = {"model": "gpt-4", "max_tokens": "4096"}  # String instead of int
        
        result = self.validator.validate(config)
        
        self.assertTrue(result.is_valid)
        self.assertIsInstance(result.validated_config["max_tokens"], int)
    
    def test_validate_range_checking(self):
        """Test range validation."""
        config = {"model": "gpt-4", "max_tokens": 999999}  # Exceeds max
        
        result = self.validator.validate(config)
        
        self.assertFalse(result.is_valid)
        self.assertTrue(any("max_tokens" in error.field for error in result.errors))
    
    def test_validate_allowed_values(self):
        """Test allowed values validation."""
        config = {"model": "gpt-4", "log_level": "INVALID"}
        
        result = self.validator.validate(config)
        
        self.assertFalse(result.is_valid)
        self.assertTrue(any("log_level" in error.field for error in result.errors))
    
    def test_validate_unknown_fields(self):
        """Test handling of unknown fields."""
        config = {"model": "gpt-4", "unknown_field": "value"}
        
        result = self.validator.validate(config)
        
        self.assertTrue(result.is_valid)  # Unknown fields should generate warnings, not errors
        self.assertGreater(len(result.warnings), 0)
    
    def test_validate_security_policy(self):
        """Test security policy validation."""
        config = {
            "model": "gpt-4",
            "confirm_dangerous_operations": False,
            "enable_audit_logging": False,
        }
        
        result = self.validator.validate(config)
        
        # Should generate warnings but not errors
        self.assertTrue(result.is_valid)
        self.assertGreater(len(result.warnings), 0)


class TestValidateConfigFile(unittest.TestCase):
    """Test configuration file validation."""

    def test_validate_json_file(self):
        """Test validating a JSON configuration file."""
        with TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "config.json"
            config_file.write_text('{"model": "gpt-4", "max_tokens": 4096}')
            
            result = validate_config_file(config_file)
            
            self.assertTrue(result.is_valid)
    
    def test_validate_nonexistent_file(self):
        """Test validating a non-existent file."""
        result = validate_config_file("/nonexistent/path/config.json")
        
        self.assertFalse(result.is_valid)
        self.assertGreater(len(result.errors), 0)
    
    def test_validate_invalid_json(self):
        """Test validating invalid JSON."""
        with TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "config.json"
            config_file.write_text('{"model": "gpt-4", "max_tokens": invalid}')
            
            result = validate_config_file(config_file)
            
            self.assertFalse(result.is_valid)


class TestGetDefaultConfig(unittest.TestCase):
    """Test default configuration retrieval."""

    def test_get_default_config(self):
        """Test getting default configuration."""
        config = get_default_config()
        
        self.assertIsInstance(config, dict)
        self.assertIn("temperature", config)
        self.assertIn("timeout", config)
        self.assertIn("max_tokens", config)


class TestGenerateConfigTemplate(unittest.TestCase):
    """Test configuration template generation."""

    def test_generate_template(self):
        """Test generating configuration template."""
        template = generate_config_template()
        
        self.assertIsInstance(template, str)
        self.assertIn("# Aider Configuration Template", template)
        self.assertIn("model:", template)
        self.assertIn("max_tokens:", template)
    
    def test_generate_template_to_file(self):
        """Test generating template to file."""
        with TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "config_template.yaml"
            generate_config_template(output_path)
            
            self.assertTrue(output_path.exists())
            content = output_path.read_text()
            self.assertIn("# Aider Configuration Template", content)


if __name__ == "__main__":
    unittest.main()
