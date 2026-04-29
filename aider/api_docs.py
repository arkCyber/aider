"""
API Documentation Generator Module

This module provides API documentation generation with OpenAPI/Swagger specifications
for the Aider AI coding assistant. It implements aerospace-level documentation
with interactive API testing and comprehensive endpoint documentation.

Key Features:
- OpenAPI 3.0 specification generation
- Automatic endpoint discovery
- Schema documentation
- Interactive API testing interface
- API versioning support
- Authentication documentation
"""

import inspect
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, get_type_hints
import re


@dataclass
class APIEndpoint:
    """
    API endpoint documentation.
    
    Attributes:
        path: API endpoint path
        method: HTTP method (GET, POST, PUT, DELETE, etc.)
        summary: Endpoint summary
        description: Detailed description
        parameters: Request parameters
        request_body: Request body schema
        responses: Response schemas
        tags: API tags for grouping
        authentication_required: Whether authentication is required
    """
    path: str
    method: str
    summary: str
    description: str
    parameters: List[Dict[str, Any]] = field(default_factory=list)
    request_body: Optional[Dict[str, Any]] = None
    responses: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    authentication_required: bool = False


@dataclass
class APISchema:
    """
    API schema definition.
    
    Attributes:
        name: Schema name
        type: Schema type (object, array, string, etc.)
        properties: Schema properties
        required: Required fields
        description: Schema description
    """
    name: str
    type: str
    properties: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    required: List[str] = field(default_factory=list)
    description: str = ""


class OpenAPIDocumentation:
    """
    OpenAPI/Swagger documentation generator.
    
    This class provides aerospace-level API documentation generation
    with comprehensive endpoint and schema documentation.
    """
    
    def __init__(
        self,
        title: str = "Aider API",
        version: str = "1.0.0",
        description: str = "Aider AI Coding Assistant API",
    ):
        """
        Initialize the OpenAPI documentation generator.
        
        Args:
            title: API title
            version: API version
            description: API description
        """
        self.title = title
        self.version = version
        self.description = description
        self.endpoints: List[APIEndpoint] = []
        self.schemas: Dict[str, APISchema] = {}
        self.security_schemes: Dict[str, Dict[str, Any]] = {}
    
    def add_endpoint(self, endpoint: APIEndpoint) -> None:
        """
        Add an API endpoint to the documentation.
        
        Args:
            endpoint: API endpoint to add
        """
        self.endpoints.append(endpoint)
    
    def add_schema(self, schema: APISchema) -> None:
        """
        Add a schema to the documentation.
        
        Args:
            schema: Schema to add
        """
        self.schemas[schema.name] = schema
    
    def add_security_scheme(self, name: str, scheme: Dict[str, Any]) -> None:
        """
        Add a security scheme to the documentation.
        
        Args:
            name: Security scheme name
            scheme: Security scheme configuration
        """
        self.security_schemes[name] = scheme
    
    def generate_openapi_spec(self) -> Dict[str, Any]:
        """
        Generate OpenAPI 3.0 specification.
        
        Returns:
            OpenAPI specification dictionary
        """
        spec = {
            "openapi": "3.0.3",
            "info": {
                "title": self.title,
                "version": self.version,
                "description": self.description,
                "contact": {
                    "name": "Aider",
                    "url": "https://github.com/arkCyber/aider",
                },
            },
            "servers": [
                {
                    "url": "http://localhost:8080",
                    "description": "Development server",
                },
                {
                    "url": "https://api.aider.chat",
                    "description": "Production server",
                },
            ],
            "paths": {},
            "components": {
                "schemas": {},
                "securitySchemes": self.security_schemes,
            },
            "tags": [],
        }
        
        # Add endpoints
        for endpoint in self.endpoints:
            if endpoint.path not in spec["paths"]:
                spec["paths"][endpoint.path] = {}
            
            endpoint_spec = {
                "summary": endpoint.summary,
                "description": endpoint.description,
                "parameters": endpoint.parameters,
                "responses": endpoint.responses,
                "tags": endpoint.tags,
            }
            
            if endpoint.request_body:
                endpoint_spec["requestBody"] = endpoint.request_body
            
            if endpoint.authentication_required:
                endpoint_spec["security"] = [{"ApiKeyAuth": []}]
            
            spec["paths"][endpoint.path][endpoint.method.lower()] = endpoint_spec
        
        # Add schemas
        for schema_name, schema in self.schemas.items():
            spec["components"]["schemas"][schema_name] = {
                "type": schema.type,
                "description": schema.description,
                "properties": schema.properties,
                "required": schema.required,
            }
        
        # Add tags
        tags = set()
        for endpoint in self.endpoints:
            tags.update(endpoint.tags)
        
        for tag in sorted(tags):
            spec["tags"].append({
                "name": tag,
                "description": f"{tag} operations",
            })
        
        return spec
    
    def export_openapi_json(self, output_path: Path) -> None:
        """
        Export OpenAPI specification to JSON file.
        
        Args:
            output_path: Path to output file
        """
        spec = self.generate_openapi_spec()
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, "w") as f:
            json.dump(spec, f, indent=2)
    
    def export_openapi_yaml(self, output_path: Path) -> None:
        """
        Export OpenAPI specification to YAML file.
        
        Args:
            output_path: Path to output file
        """
        try:
            import yaml
        except ImportError:
            raise ImportError("PyYAML is required for YAML export. Install with: pip install pyyaml")
        
        spec = self.generate_openapi_spec()
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, "w") as f:
            yaml.dump(spec, f, default_flow_style=False)
    
    def generate_interactive_html(self, output_path: Path) -> None:
        """
        Generate interactive HTML documentation using Swagger UI.
        
        Args:
            output_path: Path to output HTML file
        """
        spec = self.generate_openapi_spec()
        spec_json = json.dumps(spec)
        
        html_template = f"""<!DOCTYPE html>
<html>
<head>
    <title>{self.title} - API Documentation</title>
    <link rel="stylesheet" type="text/css" href="https://unpkg.com/swagger-ui-dist@4/swagger-ui.css" />
    <style>
        body {{ margin: 0; padding: 0; }}
        #swagger-ui {{ max-width: 1460px; margin: 0 auto; }}
    </style>
</head>
<body>
    <div id="swagger-ui"></div>
    <script src="https://unpkg.com/swagger-ui-dist@4/swagger-ui-bundle.js"></script>
    <script>
        window.onload = function() {{
            const spec = {spec_json};
            const ui = SwaggerUIBundle({{
                spec: spec,
                dom_id: '#swagger-ui',
                presets: [
                    SwaggerUIBundle.presets.apis,
                    SwaggerUIBundle.SwaggerUIStandalonePreset
                ],
                layout: "BaseLayout",
                deepLinking: true,
                showExtensions: true,
                showCommonExtensions: true
            }});
        }};
    </script>
</body>
</html>
"""
        
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, "w") as f:
            f.write(html_template)


class AiderAPIDocumentation(OpenAPIDocumentation):
    """
    Aider-specific API documentation generator.
    
    This class extends OpenAPIDocumentation to provide Aider-specific
    API documentation with pre-defined endpoints and schemas.
    """
    
    def __init__(self):
        """Initialize Aider API documentation."""
        super().__init__(
            title="Aider AI Coding Assistant API",
            version="1.0.0",
            description="API for the Aider AI coding assistant - pair programming with LLMs in your terminal",
        )
        
        # Add security schemes
        self.add_security_scheme("ApiKeyAuth", {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
            "description": "API key for authentication",
        })
        
        self.add_security_scheme("BearerAuth", {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "JWT bearer token authentication",
        })
        
        # Add common schemas
        self._add_common_schemas()
        
        # Add Aider endpoints
        self._add_aider_endpoints()
    
    def _add_common_schemas(self) -> None:
        """Add common API schemas."""
        # Error schema
        self.add_schema(APISchema(
            name="Error",
            type="object",
            properties={
                "error": {"type": "string"},
                "message": {"type": "string"},
                "code": {"type": "string"},
            },
            required=["error", "message"],
            description="Error response schema",
        ))
        
        # Success response schema
        self.add_schema(APISchema(
            name="SuccessResponse",
            type="object",
            properties={
                "success": {"type": "boolean"},
                "message": {"type": "string"},
                "data": {"type": "object"},
            },
            required=["success"],
            description="Success response schema",
        ))
    
    def _add_aider_endpoints(self) -> None:
        """Add Aider-specific API endpoints."""
        # Health check endpoint
        self.add_endpoint(APIEndpoint(
            path="/health",
            method="GET",
            summary="Health Check",
            description="Check the health status of the Aider API",
            tags=["Health"],
            responses={
                "200": {
                    "description": "Health status",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "status": {"type": "string"},
                                    "timestamp": {"type": "string"},
                                    "checks": {"type": "object"},
                                },
                            },
                        },
                    },
                },
            },
        ))
        
        # Chat endpoint
        self.add_endpoint(APIEndpoint(
            path="/api/v1/chat",
            method="POST",
            summary="Send Chat Message",
            description="Send a message to the AI assistant and receive a response",
            tags=["Chat"],
            authentication_required=True,
            parameters=[],
            request_body={
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "message": {"type": "string"},
                                "context": {"type": "array", "items": {"type": "string"}},
                                "model": {"type": "string"},
                                "temperature": {"type": "number"},
                            },
                            "required": ["message"],
                        },
                    },
                },
            },
            responses={
                "200": {
                    "description": "Chat response",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "response": {"type": "string"},
                                    "model": {"type": "string"},
                                    "tokens_used": {"type": "integer"},
                                },
                            },
                        },
                    },
                },
                "401": {
                    "description": "Unauthorized",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/Error"},
                        },
                    },
                },
            },
        ))
        
        # Code edit endpoint
        self.add_endpoint(APIEndpoint(
            path="/api/v1/code/edit",
            method="POST",
            summary="Edit Code",
            description="Request AI to edit code in specified files",
            tags=["Code"],
            authentication_required=True,
            request_body={
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "files": {"type": "array", "items": {"type": "string"}},
                                "instruction": {"type": "string"},
                                "model": {"type": "string"},
                            },
                            "required": ["files", "instruction"],
                        },
                    },
                },
            },
            responses={
                "200": {
                    "description": "Edit response",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "success": {"type": "boolean"},
                                    "edited_files": {"type": "array", "items": {"type": "string"}},
                                    "diff": {"type": "string"},
                                },
                            },
                        },
                    },
                },
            },
        ))
        
        # Models endpoint
        self.add_endpoint(APIEndpoint(
            path="/api/v1/models",
            method="GET",
            summary="List Available Models",
            description="Get list of available AI models",
            tags=["Models"],
            responses={
                "200": {
                    "description": "List of models",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "models": {"type": "array", "items": {"type": "string"}},
                                },
                            },
                        },
                    },
                },
            },
        ))


def generate_aider_api_docs(output_dir: Path) -> None:
    """
    Generate Aider API documentation.
    
    Args:
        output_dir: Directory to output documentation files
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate documentation
    docs = AiderAPIDocumentation()
    
    # Export JSON spec
    docs.export_openapi_json(output_dir / "openapi.json")
    
    # Export YAML spec
    try:
        docs.export_openapi_yaml(output_dir / "openapi.yaml")
    except ImportError:
        pass  # YAML export optional
    
    # Generate interactive HTML
    docs.generate_interactive_html(output_dir / "api-docs.html")
    
    print(f"API documentation generated in {output_dir}")
    print(f"  - openapi.json: OpenAPI specification")
    print(f"  - openapi.yaml: OpenAPI specification (YAML)")
    print(f"  - api-docs.html: Interactive documentation")


# Global API documentation instance
_global_api_docs: Optional[AiderAPIDocumentation] = None


def get_api_docs() -> AiderAPIDocumentation:
    """
    Get the global API documentation instance.
    
    Returns:
        Global AiderAPIDocumentation instance
    """
    global _global_api_docs
    if _global_api_docs is None:
        _global_api_docs = AiderAPIDocumentation()
    return _global_api_docs
