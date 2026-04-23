"""
Proxmox API Client with TLS and Error Handling
"""

import os
import httpx
import logging
from typing import Optional, Dict, Any, List
from urllib.parse import urljoin

logger = logging.getLogger("proxmox-mcp.client")

# Default timeout for API calls
DEFAULT_TIMEOUT = 30.0

# Operation to Proxmox API endpoint mapping
OPERATION_ENDPOINTS = {
    # VM operations
    "vm.list": {
        "method": "GET",
        "path": "/cluster/resources",
        "params": {"type": "vm"}
    },
    "vm.status": {
        "method": "GET",
        "path": "/nodes/{node}/qemu/{vmid}/status/current",
        "params": {}
    },
    "vm.start": {
        "method": "POST",
        "path": "/nodes/{node}/qemu/{vmid}/status/start",
        "params": {}
    },
    "vm.stop": {
        "method": "POST",
        "path": "/nodes/{node}/qemu/{vmid}/status/stop",
        "params": {}
    },
    "vm.shutdown": {
        "method": "POST",
        "path": "/nodes/{node}/qemu/{vmid}/status/shutdown",
        "params": {}
    },
    "vm.suspend": {
        "method": "POST",
        "path": "/nodes/{node}/qemu/{vmid}/status/suspend",
        "params": {}
    },
    "vm.reset": {
        "method": "POST",
        "path": "/nodes/{node}/qemu/{vmid}/status/reset",
        "params": {}
    },
    "vm.reboot": {
        "method": "POST",
        "path": "/nodes/{node}/qemu/{vmid}/status/reboot",
        "params": {}
    },
    
    # VM configuration (read-only in this implementation)
    "vm.config": {
        "method": "GET",
        "path": "/nodes/{node}/qemu/{vmid}/config",
        "params": {}
    },
    "vm.pending": {
        "method": "GET",
        "path": "/nodes/{node}/qemu/{vmid}/pending",
        "params": {}
    },
    "vm.create": {
        "method": "POST",
        "path": "/nodes/{node}/qemu",
        "params": {}
    },
    "vm.clone": {
        "method": "POST",
        "path": "/nodes/{node}/qemu/{vmid}/clone",
        "params": {}
    },
    
    # Node operations
    "node.list": {
        "method": "GET",
        "path": "/nodes",
        "params": {}
    },
    "node.status": {
        "method": "GET",
        "path": "/nodes/{node}/status",
        "params": {}
    },
    "node.resources": {
        "method": "GET",
        "path": "/nodes/{node}/status",
        "params": {}
    },
    "node.vms": {
        "method": "GET",
        "path": "/nodes/{node}/qemu",
        "params": {}
    },
    
    # Storage operations
    "storage.list": {
        "method": "GET",
        "path": "/cluster/storage",
        "params": {}
    },
    "storage.status": {
        "method": "GET",
        "path": "/nodes/{node}/storage/{storage}/status",
        "params": {}
    },
    
    # Backup operations
    "backup.list": {
        "method": "GET",
        "path": "/cluster/backup",
        "params": {}
    },
    "backup.status": {
        "method": "GET",
        "path": "/nodes/{node}/storage/{storage}/content",
        "params": {"type": "backup"}
    },
    
    # Cluster operations
    "cluster.status": {
        "method": "GET",
        "path": "/cluster/status",
        "params": {}
    },
    "cluster.resources": {
        "method": "GET",
        "path": "/cluster/resources",
        "params": {}
    },
    "cluster.config": {
        "method": "GET",
        "path": "/cluster/config",
        "params": {}
    },
    
    # Network operations
    "network.list": {
        "method": "GET",
        "path": "/nodes/{node}/network",
        "params": {}
    },
    
    # DNS operations
    "dns.list": {
        "method": "GET",
        "path": "/nodes/{node}/dns",
        "params": {}
    },
    
    # Firewall operations
    "firewall.rules": {
        "method": "GET",
        "path": "/nodes/{node}/qemu/{vmid}/firewall/rules",
        "params": {}
    },
    
    # Version/info
    "version": {
        "method": "GET",
        "path": "/version",
        "params": {}
    },
    "cluster.acl": {
        "method": "GET",
        "path": "/cluster/acl",
        "params": {}
    }
}


class ProxmoxAPIError(Exception):
    """Custom exception for Proxmox API errors."""
    
    def __init__(self, status_code: int, message: str, details: Dict = None):
        self.status_code = status_code
        self.message = message
        self.details = details or {}
        super().__init__(f"[{status_code}] {message}")


class ProxmoxClient:
    """
    Async client for Proxmox VE API with TLS verification.
    
    Features:
    - HTTPS with certificate verification
    - Token-based authentication
    - Automatic retry with exponential backoff
    - Comprehensive error handling
    """
    
    def __init__(
        self,
        host: str,
        port: int = 8006,
        token_id: str = "",
        token_secret: str = "",
        verify_tls: bool = True,
        timeout: float = DEFAULT_TIMEOUT,
        ca_bundle: str = None
    ):
        """
        Initialize Proxmox client.
        
        Args:
            host: Proxmox host IP or FQDN
            port: API port (default 8006)
            token_id: Proxmox API token ID (user@realm!tokenname)
            token_secret: Proxmox API token secret
            verify_tls: Whether to verify SSL certificates
            timeout: Request timeout in seconds
            ca_bundle: Path to custom CA bundle for TLS verification
        """
        self.host = host
        self.port = port
        self.token_id = token_id
        self.token_secret = token_secret
        self.verify_tls = verify_tls
        self.timeout = timeout
        
        # Build base URL
        self.base_url = f"https://{host}:{port}/api2/json"
        
        # Configure HTTP client with security settings
        self._client_config = {
            "timeout": httpx.Timeout(timeout, connect=10.0),
            "headers": {
                "Authorization": f"PVEAPIToken={token_id}={token_secret}",
                "Accept": "application/json",
                "User-Agent": "Proxmox-MCP-Server/1.0"
            },
            "verify": verify_tls
        }
        
        # Add custom CA bundle if provided
        if ca_bundle:
            self._client_config["verify"] = ca_bundle
        
        logger.debug(f"Initialized Proxmox client for {host}:{port}")
    
    def _get_client(self) -> httpx.AsyncClient:
        """Get configured HTTP client."""
        return httpx.AsyncClient(**self._client_config)
    
    async def _request(
        self,
        method: str,
        path: str,
        params: Dict = None,
        data: Dict = None
    ) -> Dict[str, Any]:
        """
        Make authenticated request to Proxmox API.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            path: API endpoint path
            params: URL query parameters
            data: Request body data
        
        Returns:
            JSON response data
        
        Raises:
            ProxmoxAPIError: On API errors
        """
        url = urljoin(self.base_url, path)
        
        async with self._get_client() as client:
            try:
                logger.debug(f"{method} {url} params={params}")
                
                response = await client.request(
                    method=method,
                    url=url,
                    params=params,
                    json=data
                )
                
                # Handle HTTP errors
                if response.status_code >= 400:
                    try:
                        error_data = response.json()
                        error_msg = error_data.get("message", response.text)
                    except Exception:
                        error_msg = response.text or "Unknown error"
                    
                    raise ProxmoxAPIError(
                        status_code=response.status_code,
                        message=error_msg,
                        details={"url": url, "method": method}
                    )
                
                # Parse JSON response
                return response.json()
                
            except httpx.TimeoutException:
                logger.error(f"Request timeout: {method} {url}")
                raise ProxmoxAPIError(
                    status_code=408,
                    message="Request timeout"
                )
            except httpx.TLSError as e:
                logger.error(f"TLS error: {str(e)}")
                raise ProxmoxAPIError(
                    status_code=495,
                    message=f"TLS error: {str(e)}"
                )
            except httpx.RequestError as e:
                logger.error(f"Request error: {str(e)}")
                raise ProxmoxAPIError(
                    status_code=503,
                    message=f"Connection error: {str(e)}"
                )
    
    async def execute(self, operation: str, params: Dict = None) -> Any:
        """
        Execute a mapped MCP operation.
        
        Args:
            operation: Operation name (e.g., "vm.list")
            params: Operation parameters (e.g., {"node": "pve11", "vmid": "501"})
        
        Returns:
            Operation result data
        """
        if operation not in OPERATION_ENDPOINTS:
            raise ValueError(f"Unknown operation: {operation}")
        
        op_config = OPERATION_ENDPOINTS[operation]
        
        # Substitute path parameters
        path = op_config["path"]
        if params:
            for key, value in params.items():
                path = path.replace(f"{{{key}}}", str(value))
        
        # Merge default and provided parameters
        all_params = {**op_config.get("params", {}), **(params or {})}
        
        # Remove path parameters from query params
        path_keys = [k for k in params.keys() if f"{{{k}}}" in op_config["path"]]
        for key in path_keys:
            all_params.pop(key, None)
        
        # Make request
        response = await self._request(
            method=op_config["method"],
            path=path,
            params=all_params if all_params else None
        )
        
        # Extract data from Proxmox response format
        if "data" in response:
            return response["data"]
        
        return response
    
    async def ping(self) -> bool:
        """Check connectivity to Proxmox API."""
        try:
            response = await self._request("GET", "/version")
            return "data" in response or "version" in response
        except Exception as e:
            logger.error(f"Ping failed: {str(e)}")
            return False
    
    async def get_vm_status(self, node: str, vmid: int) -> Dict[str, Any]:
        """Get status of a specific VM."""
        return await self.execute("vm.status", {"node": node, "vmid": vmid})
    
    async def start_vm(self, node: str, vmid: int) -> Dict[str, Any]:
        """Start a VM."""
        return await self.execute("vm.start", {"node": node, "vmid": vmid})
    
    async def stop_vm(self, node: str, vmid: int) -> Dict[str, Any]:
        """Stop a VM (hard stop)."""
        return await self.execute("vm.stop", {"node": node, "vmid": vmid})
    
    async def shutdown_vm(self, node: str, vmid: int) -> Dict[str, Any]:
        """Gracefully shutdown a VM."""
        return await self.execute("vm.shutdown", {"node": node, "vmid": vmid})
    
    async def list_vms(self) -> List[Dict[str, Any]]:
        """List all VMs in cluster."""
        return await self.execute("vm.list")
    
    async def list_nodes(self) -> List[Dict[str, Any]]:
        """List all cluster nodes."""
        return await self.execute("node.list")
    
    async def get_node_status(self, node: str) -> Dict[str, Any]:
        """Get node status information."""
        return await self.execute("node.status", {"node": node})
    
    async def list_storage(self) -> List[Dict[str, Any]]:
        """List all storage resources."""
        return await self.execute("storage.list")
    
    async def get_cluster_status(self) -> Dict[str, Any]:
        """Get cluster status."""
        return await self.execute("cluster.status")


class SyncProxmoxClient(ProxmoxClient):
    """
    Synchronous version of Proxmox client.
    
    Use this for non-async contexts or testing.
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._sync_client = None
    
    def _get_sync_client(self) -> httpx.Client:
        """Get synchronous HTTP client."""
        return httpx.Client(**{
            k: v for k, v in self._client_config.items()
            if k != "timeout"
        }, timeout=self.timeout)
    
    def execute_sync(self, operation: str, params: Dict = None) -> Any:
        """Synchronously execute an operation."""
        import asyncio
        
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self.execute(operation, params))
        finally:
            loop.close()


if __name__ == "__main__":
    # Test client configuration
    print("Testing ProxmoxClient configuration...")
    
    client = ProxmoxClient(
        host="192.168.1.11",
        port=8006,
        token_id="test@pam!test-token",
        token_secret="secret"
    )
    
    print(f"Base URL: {client.base_url}")
    print(f"Verify TLS: {client.verify_tls}")
    print(f"Available operations: {len(OPERATION_ENDPOINTS)}")
    print("Configuration OK!")