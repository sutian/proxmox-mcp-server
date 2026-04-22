"""
Tests for MCP server API endpoints
"""

import pytest
from httpx import AsyncClient, ASGITransport

# Import after environment is set
from server import app, DENIED_OPS, ALLOWED_OPS
from auth import create_token


@pytest.mark.asyncio
class TestHealthEndpoints:
    """Tests for health check endpoints."""
    
    async def test_health_check(self):
        """Test /health endpoint returns healthy status."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response = await client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data
        assert "version" in data
    
    async def test_root_endpoint(self):
        """Test root endpoint returns service info."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response = await client.get("/")
        
        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "Proxmox MCP Server"
        assert "version" in data


@pytest.mark.asyncio
class TestAuthenticationEndpoints:
    """Tests for authentication endpoints."""
    
    async def test_get_token_with_valid_credentials(self):
        """Test token endpoint with valid credentials."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response = await client.post(
                "/auth/token",
                json={"username": "testuser", "password": "testpass"}
            )
        
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["expires_in"] == 900
    
    async def test_get_token_with_empty_username(self):
        """Test token endpoint rejects empty username."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response = await client.post(
                "/auth/token",
                json={"username": "", "password": "testpass"}
            )
        
        assert response.status_code == 422  # Validation error
    
    async def test_refresh_token_with_valid_token(self, valid_token):
        """Test token refresh with valid token."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response = await client.post(
                "/auth/refresh",
                headers={"Authorization": f"Bearer {valid_token}"}
            )
        
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
    
    async def test_refresh_token_without_header(self):
        """Test token refresh fails without auth header."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response = await client.post("/auth/refresh")
        
        assert response.status_code == 401
    
    async def test_refresh_token_with_invalid_token(self):
        """Test token refresh fails with invalid token."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response = await client.post(
                "/auth/refresh",
                headers={"Authorization": "Bearer invalid.token.here"}
            )
        
        assert response.status_code == 401


@pytest.mark.asyncio
class TestMCPOperations:
    """Tests for MCP operation endpoints."""
    
    async def test_mcp_call_without_auth(self, sample_mcp_request):
        """Test MCP call fails without authorization."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response = await client.post(
                "/mcp/v1/call",
                json=sample_mcp_request
            )
        
        assert response.status_code == 401
    
    async def test_mcp_call_with_valid_token(self, auth_headers, sample_mcp_request):
        """Test MCP call succeeds with valid token."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response = await client.post(
                "/mcp/v1/call",
                json=sample_mcp_request,
                headers=auth_headers
            )
        
        assert response.status_code == 200
        data = response.json()
        assert "success" in data
    
    async def test_mcp_call_denied_operation(self, auth_headers):
        """Test MCP call fails for denied operations."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response = await client.post(
                "/mcp/v1/call",
                json={
                    "method": "vm.delete",
                    "params": {"node": "pve11", "vmid": 501},
                    "resource": "/nodes/pve11/qemu/501"
                },
                headers=auth_headers
            )
        
        assert response.status_code == 403
        data = response.json()
        assert "prohibited" in data["detail"].lower() or "denied" in data["detail"].lower()
    
    async def test_mcp_call_invalid_operation(self, auth_headers):
        """Test MCP call fails for unknown operations."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response = await client.post(
                "/mcp/v1/call",
                json={
                    "method": "vm.doesnotexist",
                    "params": {},
                    "resource": "/"
                },
                headers=auth_headers
            )
        
        assert response.status_code == 400
        data = response.json()
        assert "not allowed" in data["detail"].lower()
    
    async def test_list_operations_with_auth(self, auth_headers):
        """Test listing available operations."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response = await client.get(
                "/mcp/v1/operations",
                headers=auth_headers
            )
        
        assert response.status_code == 200
        data = response.json()
        assert "allowed" in data
        assert "denied" in data
        assert len(data["allowed"]) > 0


@pytest.mark.asyncio
class TestOperationAllowlist:
    """Tests for operation whitelist/blacklist."""
    
    def test_denied_operations_defined(self):
        """Test that denied operations are properly defined."""
        assert "vm.delete" in DENIED_OPS
        assert "vm.destroy" in DENIED_OPS
        assert "cluster.aclmodify" in DENIED_OPS
    
    def test_allowed_operations_defined(self):
        """Test that allowed operations are properly defined."""
        assert "vm.list" in ALLOWED_OPS
        assert "vm.status" in ALLOWED_OPS
        assert "vm.start" in ALLOWED_OPS
    
    def test_no_overlap_between_allowed_and_denied(self):
        """Test that allowed and denied operations don't overlap."""
        overlap = ALLOWED_OPS & DENIED_OPS
        assert len(overlap) == 0, f"Operations in both lists: {overlap}"


@pytest.mark.asyncio
class TestErrorHandling:
    """Tests for error handling."""
    
    async def test_invalid_json_body(self, auth_headers):
        """Test handling of invalid JSON body."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response = await client.post(
                "/mcp/v1/call",
                content=b"not valid json",
                headers={**auth_headers, "Content-Type": "application/json"}
            )
        
        # Should return error for malformed JSON
        assert response.status_code >= 400
    
    async def test_missing_required_field(self, auth_headers):
        """Test handling of missing required fields."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response = await client.post(
                "/mcp/v1/call",
                json={"params": {}},  # Missing 'method'
                headers=auth_headers
            )
        
        assert response.status_code == 422  # Validation error


@pytest.mark.asyncio
class TestCORSConfiguration:
    """Tests for CORS configuration."""
    
    async def test_cors_preflight(self):
        """Test CORS preflight request."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response = await client.options(
                "/health",
                headers={
                    "Origin": "http://localhost",
                    "Access-Control-Request-Method": "GET"
                }
            )
        
        # Should have CORS headers
        assert "access-control-allow-origin" in response.headers or \
               response.status_code == 200


@pytest.mark.asyncio
class TestServerConfiguration:
    """Tests for server configuration."""
    
    async def test_server_has_title(self):
        """Test server has proper title."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response = await client.get("/docs")
        
        # OpenAPI docs should be available
        assert response.status_code == 200
    
    async def test_openapi_schema_available(self):
        """Test OpenAPI schema is available."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response = await client.get("/openapi.json")
        
        assert response.status_code == 200
        schema = response.json()
        assert "paths" in schema
        assert "/auth/token" in schema["paths"]