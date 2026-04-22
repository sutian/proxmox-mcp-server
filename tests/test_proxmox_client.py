"""
Tests for Proxmox client module
"""

import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch

# Import after environment is set in conftest.py
from proxmox_client import (
    ProxmoxClient,
    ProxmoxAPIError,
    OPERATION_ENDPOINTS
)


class TestProxmoxClientInitialization:
    """Tests for ProxmoxClient initialization."""
    
    def test_client_initialization(self):
        """Test basic client initialization."""
        client = ProxmoxClient(
            host="192.168.1.11",
            port=8006,
            token_id="test@pam!token",
            token_secret="secret"
        )
        
        assert client.host == "192.168.1.11"
        assert client.port == 8006
        assert client.base_url == "https://192.168.1.11:8006/api2/json"
    
    def test_client_with_custom_port(self):
        """Test client with custom port."""
        client = ProxmoxClient(
            host="proxmox.example.com",
            port=443,
            token_id="test@pam!token",
            token_secret="secret"
        )
        
        assert client.port == 443
        assert client.base_url == "https://proxmox.example.com:443/api2/json"
    
    def test_tls_verification_enabled(self):
        """Test TLS verification is enabled by default."""
        client = ProxmoxClient(
            host="192.168.1.11",
            token_id="test",
            token_secret="secret"
        )
        
        assert client.verify_tls is True
    
    def test_tls_verification_disabled(self):
        """Test TLS verification can be disabled."""
        client = ProxmoxClient(
            host="192.168.1.11",
            token_id="test",
            token_secret="secret",
            verify_tls=False
        )
        
        assert client.verify_tls is False


class TestOperationEndpoints:
    """Tests for operation endpoint configuration."""
    
    def test_vm_list_operation(self):
        """Test VM list operation configuration."""
        op = OPERATION_ENDPOINTS["vm.list"]
        
        assert op["method"] == "GET"
        assert op["path"] == "/cluster/resources"
        assert "type" in op["params"]
    
    def test_vm_status_operation(self):
        """Test VM status operation configuration."""
        op = OPERATION_ENDPOINTS["vm.status"]
        
        assert op["method"] == "GET"
        assert "{node}" in op["path"]
        assert "{vmid}" in op["path"]
    
    def test_vm_start_operation(self):
        """Test VM start operation configuration."""
        op = OPERATION_ENDPOINTS["vm.start"]
        
        assert op["method"] == "POST"
        assert op["path"] == "/nodes/{node}/qemu/{vmid}/status/start"
    
    def test_all_power_operations_exist(self):
        """Test all power operations are defined."""
        power_ops = ["vm.start", "vm.stop", "vm.shutdown", "vm.suspend", "vm.reset"]
        
        for op in power_ops:
            assert op in OPERATION_ENDPOINTS


class TestProxmoxAPIError:
    """Tests for ProxmoxAPIError exception."""
    
    def test_error_creation(self):
        """Test error object creation."""
        error = ProxmoxAPIError(
            status_code=404,
            message="VM not found",
            details={"vmid": 501}
        )
        
        assert error.status_code == 404
        assert error.message == "VM not found"
        assert error.details["vmid"] == 501
    
    def test_error_string_representation(self):
        """Test error string representation."""
        error = ProxmoxAPIError(
            status_code=500,
            message="Internal error"
        )
        
        error_str = str(error)
        assert "500" in error_str
        assert "Internal error" in error_str
    
    def test_error_with_details(self):
        """Test error with detailed information."""
        error = ProxmoxAPIError(
            status_code=403,
            message="Access denied",
            details={
                "url": "/nodes/pve11/qemu/501/status/stop",
                "method": "POST",
                "token_id": "test@pam!token"
            }
        )
        
        assert "403" in str(error)
        assert error.details["method"] == "POST"


@pytest.mark.asyncio
class TestProxmoxClientExecute:
    """Tests for ProxmoxClient.execute()."""
    
    async def test_execute_valid_operation(self):
        """Test executing a valid operation."""
        client = ProxmoxClient(
            host="192.168.1.11",
            token_id="test@pam!token",
            token_secret="secret"
        )
        
        # Mock the _request method
        with patch.object(client, '_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = {"data": [{"vmid": 501}]}
            
            result = await client.execute("vm.list")
            
            mock_request.assert_called_once()
            assert result == [{"vmid": 501}]
    
    async def test_execute_with_params(self):
        """Test executing operation with parameters."""
        client = ProxmoxClient(
            host="192.168.1.11",
            token_id="test@pam!token",
            token_secret="secret"
        )
        
        with patch.object(client, '_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = {"data": {"status": "running"}}
            
            result = await client.execute("vm.status", {"node": "pve11", "vmid": 501})
            
            call_args = mock_request.call_args
            assert "pve11" in call_args[1]["path"]  # Path should be substituted
    
    async def test_execute_unknown_operation(self):
        """Test executing unknown operation raises error."""
        client = ProxmoxClient(
            host="192.168.1.11",
            token_id="test@pam!token",
            token_secret="secret"
        )
        
        with pytest.raises(ValueError, match="Unknown operation"):
            await client.execute("nonexistent.operation")


@pytest.mark.asyncio
class TestClientPing:
    """Tests for ProxmoxClient.ping()."""
    
    async def test_ping_success(self):
        """Test successful ping."""
        client = ProxmoxClient(
            host="192.168.1.11",
            token_id="test@pam!token",
            token_secret="secret"
        )
        
        with patch.object(client, '_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = {"version": "8.0"}
            
            result = await client.ping()
            
            assert result is True
    
    async def test_ping_failure(self):
        """Test failed ping."""
        client = ProxmoxClient(
            host="192.168.1.11",
            token_id="test@pam!token",
            token_secret="secret"
        )
        
        with patch.object(client, '_request', new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = Exception("Connection refused")
            
            result = await client.ping()
            
            assert result is False


class TestHelperMethods:
    """Tests for ProxmoxClient helper methods."""
    
    @pytest.mark.asyncio
    async def test_get_vm_status(self):
        """Test get_vm_status helper."""
        client = ProxmoxClient(
            host="192.168.1.11",
            token_id="test@pam!token",
            token_secret="secret"
        )
        
        with patch.object(client, 'execute', new_callable=AsyncMock) as mock_execute:
            mock_execute.return_value = {"status": "running", "uptime": 3600}
            
            result = await client.get_vm_status("pve11", 501)
            
            mock_execute.assert_called_with("vm.status", {"node": "pve11", "vmid": 501})
            assert result["status"] == "running"
    
    @pytest.mark.asyncio
    async def test_start_vm(self):
        """Test start_vm helper."""
        client = ProxmoxClient(
            host="192.168.1.11",
            token_id="test@pam!token",
            token_secret="secret"
        )
        
        with patch.object(client, 'execute', new_callable=AsyncMock) as mock_execute:
            mock_execute.return_value = {"status": "OK"}
            
            result = await client.start_vm("pve11", 501)
            
            mock_execute.assert_called_with("vm.start", {"node": "pve11", "vmid": 501})
    
    @pytest.mark.asyncio
    async def test_stop_vm(self):
        """Test stop_vm helper."""
        client = ProxmoxClient(
            host="192.168.1.11",
            token_id="test@pam!token",
            token_secret="secret"
        )
        
        with patch.object(client, 'execute', new_callable=AsyncMock) as mock_execute:
            mock_execute.return_value = {"status": "OK"}
            
            result = await client.stop_vm("pve11", 501)
            
            mock_execute.assert_called_with("vm.stop", {"node": "pve11", "vmid": 501})
    
    @pytest.mark.asyncio
    async def test_shutdown_vm(self):
        """Test shutdown_vm helper."""
        client = ProxmoxClient(
            host="192.168.1.11",
            token_id="test@pam!token",
            token_secret="secret"
        )
        
        with patch.object(client, 'execute', new_callable=AsyncMock) as mock_execute:
            mock_execute.return_value = {"status": "OK"}
            
            result = await client.shutdown_vm("pve11", 501)
            
            mock_execute.assert_called_with("vm.shutdown", {"node": "pve11", "vmid": 501})
    
    @pytest.mark.asyncio
    async def test_list_vms(self):
        """Test list_vms helper."""
        client = ProxmoxClient(
            host="192.168.1.11",
            token_id="test@pam!token",
            token_secret="secret"
        )
        
        with patch.object(client, 'execute', new_callable=AsyncMock) as mock_execute:
            mock_execute.return_value = [{"vmid": 501}, {"vmid": 502}]
            
            result = await client.list_vms()
            
            mock_execute.assert_called_with("vm.list")
            assert len(result) == 2
    
    @pytest.mark.asyncio
    async def test_list_nodes(self):
        """Test list_nodes helper."""
        client = ProxmoxClient(
            host="192.168.1.11",
            token_id="test@pam!token",
            token_secret="secret"
        )
        
        with patch.object(client, 'execute', new_callable=AsyncMock) as mock_execute:
            mock_execute.return_value = [{"node": "pve11"}, {"node": "pve12"}]
            
            result = await client.list_nodes()
            
            mock_execute.assert_called_with("node.list")
            assert len(result) == 2


class TestHTTPClientConfiguration:
    """Tests for HTTP client configuration."""
    
    def test_client_headers_include_auth(self):
        """Test that client headers include API token."""
        client = ProxmoxClient(
            host="192.168.1.11",
            token_id="test-user@pam!my-token",
            token_secret="secret-xyz"
        )
        
        headers = client._client_config["headers"]
        assert "Authorization" in headers
        assert "PVEAPIToken=" in headers["Authorization"]
    
    def test_client_user_agent(self):
        """Test that client sends custom User-Agent."""
        client = ProxmoxClient(
            host="192.168.1.11",
            token_id="test",
            token_secret="secret"
        )
        
        headers = client._client_config["headers"]
        assert "User-Agent" in headers
        assert "Proxmox" in headers["User-Agent"]
    
    def test_timeout_configuration(self):
        """Test client timeout is configured."""
        client = ProxmoxClient(
            host="192.168.1.11",
            token_id="test",
            token_secret="secret",
            timeout=45.0
        )
        
        assert client.timeout == 45.0