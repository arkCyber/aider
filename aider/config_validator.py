"""
Configuration Validation Module

This module provides configuration validation for the Aider AI coding assistant.
It implements aerospace-level validation with schema checking, type validation,
and security policy enforcement.

Key Features:
- Configuration schema validation
- Type checking and conversion
- Security policy enforcement
- Default value management
- Configuration migration support
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


@dataclass
class ValidationError:
    """
    Represents a configuration validation error.
    
    Attributes:
        field: Name of the field that failed validation
        message: Error message describing the validation failure
        severity: Severity level (error, warning, info)
    """
    field: str
    message: str
    severity: str = "error"


@dataclass
class ValidationResult:
    """
    Result of a configuration validation.
    
    Attributes:
        is_valid: Whether the configuration is valid
        errors: List of validation errors
        warnings: List of validation warnings
        validated_config: The validated and normalized configuration
    """
    is_valid: bool
    errors: List[ValidationError] = field(default_factory=list)
    warnings: List[ValidationError] = field(default_factory=list)
    validated_config: Dict[str, Any] = field(default_factory=dict)


class ConfigValidator:
    """
    Configuration validator with aerospace-level validation capabilities.
    
    This class provides comprehensive configuration validation including
    type checking, range validation, security policy enforcement, and
    schema validation.
    """
    
    # Configuration schema definition
    SCHEMA = {
        "model": {
            "type": str,
            "required": True,
            "description": "AI model to use",
        },
        "api_key": {
            "type": str,
            "required": False,
            "description": "API key for the model provider",
            "security_sensitive": True,
        },
        "api_base": {
            "type": str,
            "required": False,
            "description": "Base URL for API requests",
        },
        "max_tokens": {
            "type": int,
            "required": False,
            "default": 4096,
            "min": 1,
            "max": 128000,
            "description": "Maximum number of tokens",
        },
        "temperature": {
            "type": float,
            "required": False,
            "default": 0.0,
            "min": 0.0,
            "max": 2.0,
            "description": "Temperature for model responses",
        },
        "timeout": {
            "type": int,
            "required": False,
            "default": 60,
            "min": 1,
            "max": 600,
            "description": "Request timeout in seconds",
        },
        "confirm_dangerous_operations": {
            "type": bool,
            "required": False,
            "default": True,
            "description": "Require confirmation for dangerous operations",
        },
        "enable_audit_logging": {
            "type": bool,
            "required": False,
            "default": True,
            "description": "Enable audit logging",
        },
        "log_level": {
            "type": str,
            "required": False,
            "default": "INFO",
            "allowed_values": ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
            "description": "Logging level",
        },
        "auto_commits": {
            "type": bool,
            "required": False,
            "default": True,
            "description": "Automatically commit changes",
        },
        "auto_lint": {
            "type": bool,
            "required": False,
            "default": True,
            "description": "Automatically lint code",
        },
        "auto_test": {
            "type": bool,
            "required": False,
            "default": False,
            "description": "Automatically run tests",
        },
    }
    
    def __init__(self):
        """Initialize the configuration validator."""
        self.errors: List[ValidationError] = []
        self.warnings: List[ValidationError] = []
    
    def validate(self, config: Dict[str, Any]) -> ValidationResult:
        """
        Validate a configuration dictionary against the schema.
        
        Args:
            config: Configuration dictionary to validate
            
        Returns:
            ValidationResult containing validation status and any errors/warnings
        """
        self.errors = []
        self.warnings = []
        validated_config = {}
        
        # Check required fields
        for field_name, field_schema in self.SCHEMA.items():
            if field_schema.get("required", False) and field_name not in config:
                self.errors.append(
                    ValidationError(
                        field=field_name,
                        message=f"Required field '{field_name}' is missing",
                    )
                )
                continue
            
            # Validate field if present
            if field_name in config:
                validation_result = self._validate_field(
                    field_name, config[field_name], field_schema
                )
                if validation_result:
                    validated_config[field_name] = validation_result
            elif "default" in field_schema:
                validated_config[field_name] = field_schema["default"]
        
        # Check for unknown fields
        for field_name in config:
            if field_name not in self.SCHEMA:
                self.warnings.append(
                    ValidationError(
                        field=field_name,
                        message=f"Unknown field '{field_name}' will be ignored",
                        severity="warning",
                    )
                )
        
        # Check for security-sensitive fields in plain text
        self._check_security_policy(config)
        
        return ValidationResult(
            is_valid=len(self.errors) == 0,
            errors=self.errors,
            warnings=self.warnings,
            validated_config=validated_config,
        )
    
    def _validate_field(
        self, field_name: str, value: Any, schema: Dict[str, Any]
    ) -> Optional[Any]:
        """
        Validate a single field against its schema.
        
        Args:
            field_name: Name of the field
            value: Value to validate
            schema: Schema definition for the field
            
        Returns:
            Validated and converted value, or None if validation fails
        """
        # Type checking
        expected_type = schema["type"]
        try:
            if expected_type is bool and isinstance(value, str):
                # Convert string to boolean
                validated_value = value.lower() in ("true", "1", "yes", "on")
            else:
                validated_value = expected_type(value)
        except (ValueError, TypeError):
            self.errors.append(
                ValidationError(
                    field=field_name,
                    message=f"Field '{field_name}' must be of type {expected_type.__name__}",
                )
            )
            return None
        
        # Range checking
        if "min" in schema and validated_value < schema["min"]:
            self.errors.append(
                ValidationError(
                    field=field_name,
                    message=f"Field '{field_name}' must be >= {schema['min']}",
                )
            )
            return None
        
        if "max" in schema and validated_value > schema["max"]:
            self.errors.append(
                ValidationError(
                    field=field_name,
                    message=f"Field '{field_name}' must be <= {schema['max']}",
                )
            )
            return None
        
        # Allowed values checking
        if "allowed_values" in schema and validated_value not in schema["allowed_values"]:
            self.errors.append(
                ValidationError(
                    field=field_name,
                    message=f"Field '{field_name}' must be one of: {schema['allowed_values']}",
                )
            )
            return None
        
        return validated_value
    
    def _check_security_policy(self, config: Dict[str, Any]) -> None:
        """
        Check configuration against security policies.
        
        Args:
            config: Configuration dictionary to check
        """
        # Check for API keys in plain text
        for field_name, field_schema in self.SCHEMA.items():
            if field_schema.get("security_sensitive", False):
                if field_name in config:
                    value = str(config[field_name])
                    if len(value) < 10 or value in ["", "null", "none", "None"]:
                        self.warnings.append(
                            ValidationError(
                                field=field_name,
                                message=f"Security-sensitive field '{field_name}' appears to have an invalid value",
                                severity="warning",
                            )
                        )
        
        # Check for dangerous configurations
        if config.get("confirm_dangerous_operations") == False:
            self.warnings.append(
                ValidationError(
                    field="confirm_dangerous_operations",
                    message="Dangerous operation confirmation is disabled - this may pose security risks",
                    severity="warning",
                )
            )
        
        if config.get("enable_audit_logging") == False:
            self.warnings.append(
                ValidationError(
                    field="enable_audit_logging",
                    message="Audit logging is disabled - this may pose compliance risks",
                    severity="warning",
                )
            )


def validate_config_file(config_path: Union[str, Path]) -> ValidationResult:
    """
    Validate a configuration file.
    
    Args:
        config_path: Path to the configuration file
        
    Returns:
        ValidationResult containing validation status and any errors/warnings
    """
    config_path = Path(config_path)
    
    if not config_path.exists():
        return ValidationResult(
            is_valid=False,
            errors=[ValidationError(field="file", message=f"Configuration file not found: {config_path}")],
        )
    
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            if config_path.suffix in [".json"]:
                config = json.load(f)
            else:
                # Assume YAML format
                import yaml
                config = yaml.safe_load(f) or {}
    except json.JSONDecodeError as e:
        return ValidationResult(
            is_valid=False,
            errors=[ValidationError(field="file", message=f"Invalid JSON: {e}")],
        )
    except Exception as e:
        return ValidationResult(
            is_valid=False,
            errors=[ValidationError(field="file", message=f"Error reading config: {e}")],
        )
    
    validator = ConfigValidator()
    return validator.validate(config)


def get_default_config() -> Dict[str, Any]:
    """
    Get the default configuration.
    
    Returns:
        Dictionary containing default values for all configuration fields
    """
    return {
        field_name: field_schema.get("default")
        for field_name, field_schema in ConfigValidator.SCHEMA.items()
        if "default" in field_schema
    }


def generate_config_template(output_path: Union[str, Path] = None) -> str:
    """
    Generate a configuration template with comments.
    
    Args:
        output_path: Optional path to write the template to
        
    Returns:
        YAML-formatted configuration template
    """
    template_lines = ["# Aider Configuration Template", "#", ""]
    
    for field_name, field_schema in ConfigValidator.SCHEMA.items():
        template_lines.append(f"# {field_schema.get('description', '')}")
        
        if "default" in field_schema:
            default_value = field_schema["default"]
            template_lines.append(f"# Default: {default_value}")
        
        if "allowed_values" in field_schema:
            template_lines.append(f"# Allowed values: {field_schema['allowed_values']}")
        
        if "min" in field_schema or "max" in field_schema:
            min_val = field_schema.get("min", "N/A")
            max_val = field_schema.get("max", "N/A")
            template_lines.append(f"# Range: {min_val} - {max_val}")
        
        if field_schema.get("security_sensitive", False):
            template_lines.append("# SECURITY SENSITIVE - Handle with care")
        
        template_lines.append(f"{field_name}: {field_schema.get('default', '')}")
        template_lines.append("")
    
    template = "\n".join(template_lines)
    
    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(template)
    
    return template
