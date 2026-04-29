"""
Unit tests for API documentation module.
"""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from aider.api_docs import (
    APIEndpoint,
    APISchema,
    AiderAPIDocumentation,
    OpenAPIDocumentation,
    generate_aider_api_docs,
    get_api_docs,
)


class TestAPIEndpoint(unittest.TestCase):
    """Test API endpoint dataclass."""

    def test_api_endpoint_creation(self):
        """Test creating an API endpoint."""
        endpoint = APIEndpoint(
            path="/api/test",
            method="GET",
            summary="Test endpoint",
            description="Test endpoint description",
        )
        
        self.assertEqual(endpoint.path, "/api/test")
        self.assertEqual(endpoint.method, "GET")
        self.assertEqual(endpoint.summary, "Test endpoint")


class TestAPISchema(unittest.TestCase):
    """Test API schema dataclass."""

    def test_api_schema_creation(self):
        """Test creating an API schema."""
        schema = APISchema(
            name="TestSchema",
            type="object",
            properties={"field1": {"type": "string"}},
            required=["field1"],
        )
        
        self.assertEqual(schema.name, "TestSchema")
        self.assertEqual(schema.type, "object")


class TestOpenAPIDocumentation(unittest.TestCase):
    """Test OpenAPI documentation generator."""

    def setUp(self):
        """Set up test fixtures."""
        self.docs = OpenAPIDocumentation(
            title="Test API",
            version="1.0.0",
            description="Test API description",
        )
    
    def test_initialization(self):
        """Test OpenAPI documentation initialization."""
        self.assertEqual(self.docs.title, "Test API")
        self.assertEqual(self.docs.version, "1.0.0")
    
    def test_add_endpoint(self):
        """Test adding an endpoint."""
        endpoint = APIEndpoint(
            path="/api/test",
            method="GET",
            summary="Test",
            description="Test description",
        )
        self.docs.add_endpoint(endpoint)
        
        self.assertEqual(len(self.docs.endpoints), 1)
    
    def test_add_schema(self):
        """Test adding a schema."""
        schema = APISchema(
            name="TestSchema",
            type="object",
        )
        self.docs.add_schema(schema)
        
        self.assertIn("TestSchema", self.docs.schemas)
    
    def test_generate_openapi_spec(self):
        """Test generating OpenAPI specification."""
        endpoint = APIEndpoint(
            path="/api/test",
            method="GET",
            summary="Test",
            description="Test description",
        )
        self.docs.add_endpoint(endpoint)
        
        spec = self.docs.generate_openapi_spec()
        
        self.assertIsNotNone(spec)
        self.assertEqual(spec["openapi"], "3.0.3")
        self.assertEqual(spec["info"]["title"], "Test API")
        self.assertIn("/api/test", spec["paths"])
    
    def test_export_openapi_json(self):
        """Test exporting OpenAPI spec to JSON."""
        with TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "openapi.json"
            self.docs.export_openapi_json(output_path)
            
            self.assertTrue(output_path.exists())
            
            # Verify it's valid JSON
            with open(output_path) as f:
                spec = json.load(f)
                self.assertEqual(spec["openapi"], "3.0.3")


class TestAiderAPIDocumentation(unittest.TestCase):
    """Test Aider-specific API documentation."""

    def setUp(self):
        """Set up test fixtures."""
        self.docs = AiderAPIDocumentation()
    
    def test_initialization(self):
        """Test Aider API documentation initialization."""
        self.assertEqual(self.docs.title, "Aider AI Coding Assistant API")
        self.assertGreater(len(self.docs.endpoints), 0)
    
    def test_predefined_endpoints(self):
        """Test that predefined endpoints exist."""
        endpoint_paths = [e.path for e in self.docs.endpoints]
        
        self.assertIn("/health", endpoint_paths)
        self.assertIn("/api/v1/chat", endpoint_paths)
        self.assertIn("/api/v1/code/edit", endpoint_paths)
    
    def test_generate_spec(self):
        """Test generating Aider API spec."""
        spec = self.docs.generate_openapi_spec()
        
        self.assertIsNotNone(spec)
        self.assertEqual(spec["info"]["title"], "Aider AI Coding Assistant API")
        self.assertGreater(len(spec["paths"]), 0)
    
    def test_security_schemes(self):
        """Test that security schemes are defined."""
        spec = self.docs.generate_openapi_spec()
        
        self.assertIn("securitySchemes", spec["components"])
        self.assertIn("ApiKeyAuth", spec["components"]["securitySchemes"])
        self.assertIn("BearerAuth", spec["components"]["securitySchemes"])


class TestGenerateAiderAPIDocs(unittest.TestCase):
    """Test generating Aider API documentation."""

    def test_generate_aider_api_docs(self):
        """Test generating Aider API documentation files."""
        with TemporaryDirectory() as temp_dir:
            generate_aider_api_docs(Path(temp_dir))
            
            output_dir = Path(temp_dir)
            self.assertTrue((output_dir / "openapi.json").exists())
            self.assertTrue((output_dir / "api-docs.html").exists())


class TestGlobalAPIDocs(unittest.TestCase):
    """Test global API documentation instance."""

    def test_get_api_docs(self):
        """Test getting global API documentation."""
        docs = get_api_docs()
        self.assertIsNotNone(docs)
        
        # Should return same instance
        docs2 = get_api_docs()
        self.assertIs(docs, docs2)


if __name__ == "__main__":
    unittest.main()
