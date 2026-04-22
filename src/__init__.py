# Proxmox MCP Server - Source Package
__version__ = "1.0.0"
__author__ = "OxTigger"

from .server import app
from .auth import create_token, verify_token, verify_proxmox_access
from .proxmox_client import ProxmoxClient, ProxmoxAPIError
from .models import (
    MCPRequest,
    MCPResponse,
    TokenRequest,
    TokenResponse,
    HealthResponse,
    ErrorResponse
)

__all__ = [
    "app",
    "create_token",
    "verify_token", 
    "verify_proxmox_access",
    "ProxmoxClient",
    "ProxmoxAPIError",
    "MCPRequest",
    "MCPResponse",
    "TokenRequest",
    "TokenResponse",
    "HealthResponse",
    "ErrorResponse"
]