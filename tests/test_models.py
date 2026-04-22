"""
Tests for Pydantic models
"""

import pytest
from datetime import datetime, timezone

from models import (
    TokenRequest,
    TokenResponse,
    MCPRequest,
    MCPResponse,
    VMBase,
    NodeBase,
    HealthResponse,
    ErrorResponse,
    validate_vmid,
    validate_node_name
)


class TestTokenRequest:
    """Tests for TokenRequest model."""
    
    def test_valid_token_request(self):
        """Test valid token request creation."""
        request = TokenRequest(username="testuser", password="testpass123")
        
        assert request.username == "testuser"
        assert request.password == "testpass123"
    
    def test_username_normalization(self):
        """Test username is normalized (lowercase, trimmed)."""
        request = TokenRequest(username="  TestUser  ", password="test")
        
        assert request.username == "testuser"
    
    def test_empty_username_rejected(self):
        """Test empty username is rejected."""
        with pytest.raises(Exception):
            TokenRequest(username="", password="test")
    
    def test_empty_password_rejected(self):
        """Test empty password is rejected."""
        with pytest.raises(Exception):
            TokenRequest(username="test", password="")


class TestMCPRequest:
    """Tests for MCPRequest model."""
    
    def test_valid_mcp_request(self):
        """Test valid MCP request creation."""
        request = MCPRequest(
            method="vm.list",
            params={"type": "vm"},
            resource="/cluster/resources"
        )
        
        assert request.method == "vm.list"
        assert request.params["type"] == "vm"
    
    def test_default_params(self):
        """Test default empty params."""
        request = MCPRequest(method="vm.list")
        
        assert request.params == {}
        assert request.resource == "/"
    
    def test_method_validation_valid(self):
        """Test valid method names are accepted."""
        valid_methods = ["vm.list", "vm.status", "node.status", "cluster_info"]
        
        for method in valid_methods:
            request = MCPRequest(method=method)
            assert request.method == method
    
    def test_method_validation_invalid(self):
        """Test invalid method names are rejected."""
        invalid_methods = ["vm/delete", "vm:list", "vm list", ""]
        
        for method in invalid_methods:
            with pytest.raises(Exception):
                MCPRequest(method=method)
    
    def test_method_too_long(self):
        """Test overly long method names are rejected."""
        long_method = "a" * 101  # Max is 100
        
        with pytest.raises(Exception):
            MCPRequest(method=long_method)


class TestMCPResponse:
    """Tests for MCPResponse model."""
    
    def test_success_response(self):
        """Test successful response creation."""
        response = MCPResponse(
            success=True,
            data=[{"vmid": 501}],
            operation="vm.list"
        )
        
        assert response.success is True
        assert response.data == [{"vmid": 501}]
        assert response.operation == "vm.list"
        assert response.error is None
    
    def test_error_response(self):
        """Test error response creation."""
        response = MCPResponse(
            success=False,
            error="VM not found",
            operation="vm.status"
        )
        
        assert response.success is False
        assert response.error == "VM not found"
        assert response.data is None
    
    def test_timestamp_auto_generated(self):
        """Test timestamp is auto-generated."""
        response = MCPResponse(success=True)
        
        assert response.timestamp is not None
        # Should be valid ISO format
        datetime.fromisoformat(response.timestamp.replace("Z", "+00:00"))
    
    def test_request_id_optional(self):
        """Test request_id is optional."""
        response = MCPResponse(success=True)
        
        assert response.request_id is None


class TestVMBaseModel:
    """Tests for VMBase model."""
    
    def test_valid_vm_creation(self):
        """Test valid VM creation."""
        vm = VMBase(
            vmid=501,
            name="web-server",
            status="running",
            node="pve11"
        )
        
        assert vm.vmid == 501
        assert vm.name == "web-server"
        assert vm.status == "running"
    
    def test_vm_status_enum(self):
        """Test VM status accepts enum values."""
        from models import VMStatus
        
        vm = VMBase(
            vmid=501,
            name="test",
            status=VMStatus.RUNNING
        )
        
        assert vm.status == VMStatus.RUNNING
    
    def test_optional_fields(self):
        """Test optional VM fields."""
        vm = VMBase(
            vmid=501,
            name="test",
            status="stopped"
        )
        
        assert vm.node is None
        assert vm.cpu is None
        assert vm.uptime is None


class TestNodeBaseModel:
    """Tests for NodeBase model."""
    
    def test_valid_node_creation(self):
        """Test valid node creation."""
        node = NodeBase(
            node="pve11",
            status="online",
            uptime=86400
        )
        
        assert node.node == "pve11"
        assert node.status == "online"
    
    def test_optional_node_fields(self):
        """Test optional node fields."""
        node = NodeBase(node="pve11", status="online")
        
        assert node.cpu is None
        assert node.mem is None


class TestHealthResponse:
    """Tests for HealthResponse model."""
    
    def test_health_response_creation(self):
        """Test health response creation."""
        health = HealthResponse(
            status="healthy",
            timestamp="2024-01-01T00:00:00Z",
            version="1.0.0"
        )
        
        assert health.status == "healthy"
    
    def test_optional_details(self):
        """Test optional health details."""
        health = HealthResponse(
            status="unhealthy",
            timestamp="2024-01-01T00:00:00Z",
            version="1.0.0",
            details={"error": "Connection failed"}
        )
        
        assert health.details["error"] == "Connection failed"


class TestErrorResponse:
    """Tests for ErrorResponse model."""
    
    def test_error_response_creation(self):
        """Test error response creation."""
        error = ErrorResponse(
            error="Not found",
            code="404"
        )
        
        assert error.error == "Not found"
        assert error.code == "404"
    
    def test_error_timestamp_auto_generated(self):
        """Test error timestamp is auto-generated."""
        error = ErrorResponse(error="Test", code="500")
        
        assert error.timestamp is not None


class TestValidationHelpers:
    """Tests for validation helper functions."""
    
    def test_validate_vmid_valid(self):
        """Test valid VM IDs."""
        valid_ids = [1, 100, 500, 9999, 999999]
        
        for vmid in valid_ids:
            assert validate_vmid(vmid) is True
    
    def test_validate_vmid_invalid(self):
        """Test invalid VM IDs."""
        invalid_ids = [0, -1, 1000000, 9999999]
        
        for vmid in invalid_ids:
            assert validate_vmid(vmid) is False
    
    def test_validate_node_name_valid(self):
        """Test valid node names."""
        valid_names = ["pve11", "proxmox-node-1", "node1", "pve-12"]
        
        for name in valid_names:
            assert validate_node_name(name) is True
    
    def test_validate_node_name_invalid(self):
        """Test invalid node names."""
        invalid_names = ["", "-invalid", "has space", "has\ttab"]
        
        for name in invalid_names:
            assert validate_node_name(name) is False


class TestModelExamples:
    """Tests for model examples."""
    
    def test_mcp_request_examples(self):
        """Test MCP request accepts example values."""
        request = MCPRequest(
            method="vm.list",
            params={},
            resource="/cluster/resources"
        )
        
        assert request.method == "vm.list"
    
    def test_token_response_defaults(self):
        """Test TokenResponse has correct defaults."""
        response = TokenResponse(access_token="test-token")
        
        assert response.token_type == "bearer"
        assert response.expires_in == 900