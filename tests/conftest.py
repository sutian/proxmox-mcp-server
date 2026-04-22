"""
pytest configuration and fixtures
"""

import os
import pytest
import asyncio
from typing import Generator, AsyncGenerator

# Set test environment before imports
os.environ["JWT_SECRET"] = "test-secret-key-for-testing-purposes-only-32chars"
os.environ["PROXMOX_HOST"] = "test.proxmox.local"
os.environ["PROXMOX_PORT"] = "8006"
os.environ["PROXMOX_TOKEN_ID"] = "test@pam!test-token"
os.environ["PROXMOX_TOKEN_SECRET"] = "test-secret"

# Now import application modules
from auth import create_token, verify_token, verify_proxmox_access
from models import MCPRequest, TokenRequest

# ============================================================
# Pytest Fixtures
# ============================================================

@pytest.fixture(scope="session")
def event_loop() -> Generator:
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def valid_token() -> str:
    """Generate a valid JWT token for testing."""
    return create_token(
        user_id="test-user",
        role="operator",
        allowed_resources=["*/qemu/*", "/cluster/resources"]
    )


@pytest.fixture
def admin_token() -> str:
    """Generate an admin JWT token for testing."""
    return create_token(
        user_id="admin-user",
        role="admin",
        allowed_resources=["*"]
    )


@pytest.fixture
def viewer_token() -> str:
    """Generate a viewer-only JWT token for testing."""
    return create_token(
        user_id="viewer-user",
        role="viewer",
        allowed_resources=["/cluster/resources", "/nodes/*/qemu"]
    )


@pytest.fixture
def sample_mcp_request() -> dict:
    """Sample MCP request payload."""
    return {
        "method": "vm.list",
        "params": {},
        "resource": "/cluster/resources"
    }


@pytest.fixture
def sample_vm_start_request() -> dict:
    """Sample VM start request."""
    return {
        "method": "vm.start",
        "params": {"node": "pve11", "vmid": 501},
        "resource": "/nodes/pve11/qemu/501/status/start"
    }


@pytest.fixture
def auth_headers(valid_token: str) -> dict:
    """Authorization headers with valid token."""
    return {"Authorization": f"Bearer {valid_token}"}


# ============================================================
# Mock Data Fixtures
# ============================================================

@pytest.fixture
def mock_vm_list() -> list:
    """Mock VM list response from Proxmox."""
    return [
        {
            "vmid": 501,
            "name": "web-server-01",
            "status": "running",
            "node": "pve11",
            "cpu": 15.5,
            "mem": 4294967296,
            "maxmem": 8589934592,
            "uptime": 86400
        },
        {
            "vmid": 502,
            "name": "db-server-01",
            "status": "stopped",
            "node": "pve11",
            "cpu": 0,
            "mem": 0,
            "maxmem": 17179869184,
            "uptime": 0
        }
    ]


@pytest.fixture
def mock_node_status() -> dict:
    """Mock node status response."""
    return {
        "node": "pve11",
        "status": "online",
        "uptime": 2592000,
        "cpu": 25.5,
        "mem": 68719476736,
        "maxmem": 137438953472,
        "disk": 512000000000,
        "max_disk": 1024000000000
    }


# ============================================================
# Test Client Fixture
# ============================================================

@pytest.fixture
async def test_client():
    """Create test client for async API testing."""
    from httpx import AsyncClient, ASGITransport
    from server import app
    
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as client:
        yield client