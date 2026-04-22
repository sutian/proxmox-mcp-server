"""
Pydantic models for request/response validation
"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum

# ============================================================
# Enums
# ============================================================

class OperationRisk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class UserRole(str, Enum):
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"

class VMStatus(str, Enum):
    RUNNING = "running"
    STOPPED = "stopped"
    SUSPENDED = "suspended"
    PAUSED = "paused"
    UNKNOWN = "unknown"

# ============================================================
# Auth Models
# ============================================================

class TokenRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=256)
    password: str = Field(..., min_length=1)
    
    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        # Basic sanitization
        return v.strip().lower()


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(default=900, description="Token validity in seconds")
    scope: Optional[str] = None


class TokenIntrospectionResponse(BaseModel):
    active: bool
    token_type: Optional[str] = "Bearer"
    scope: Optional[str] = None
    exp: Optional[int] = None
    iat: Optional[int] = None
    sub: Optional[str] = None
    role: Optional[str] = None


# ============================================================
# MCP Models
# ============================================================

class MCPRequest(BaseModel):
    method: str = Field(
        ...,
        description="MCP operation method (e.g., 'vm.list', 'vm.start')",
        examples=["vm.list", "vm.start"]
    )
    params: Dict[str, Any] = Field(
        default_factory=dict,
        description="Operation parameters (e.g., {'node': 'pve11', 'vmid': 501})"
    )
    resource: str = Field(
        default="/",
        description="Proxmox resource path for access control",
        examples=["/nodes/pve11/qemu/501", "/cluster/resources"]
    )
    
    @field_validator("method")
    @classmethod
    def validate_method(cls, v: str) -> str:
        if not v or len(v) > 100:
            raise ValueError("Invalid method name")
        # Only allow alphanumeric, dots, underscores
        if not all(c.isalnum() or c in "._" for c in v):
            raise ValueError("Method contains invalid characters")
        return v


class MCPResponse(BaseModel):
    success: bool = Field(..., description="Whether operation succeeded")
    data: Optional[Any] = Field(None, description="Operation result data")
    error: Optional[str] = Field(None, description="Error message if failed")
    operation: Optional[str] = Field(None, description="The operation that was executed")
    timestamp: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat(),
        description="Response timestamp"
    )
    request_id: Optional[str] = Field(None, description="Request correlation ID")


class MCPOperationInfo(BaseModel):
    name: str
    description: Optional[str] = None
    risk_level: OperationRisk = OperationRisk.LOW
    params_required: List[str] = Field(default_factory=list)
    params_optional: List[str] = Field(default_factory=list)


class MCPOperationListResponse(BaseModel):
    allowed: List[str] = Field(..., description="List of allowed operations")
    denied: List[str] = Field(..., description="List of denied/blocked operations")
    total_allowed: int
    total_denied: int
    operations: Optional[List[MCPOperationInfo]] = None


# ============================================================
# Proxmox Resource Models
# ============================================================

class VMBase(BaseModel):
    """Base VM information model."""
    vmid: int = Field(..., description="VM ID")
    name: str = Field(..., description="VM name")
    status: VMStatus = Field(..., description="Current VM status")
    node: Optional[str] = Field(None, description="Node where VM is running")
    cpu: Optional[float] = Field(None, description="CPU usage percentage")
    mem: Optional[int] = Field(None, description="Memory usage in bytes")
    max_mem: Optional[int] = Field(None, description="Maximum memory in bytes")
    disk: Optional[int] = Field(None, description="Disk usage in bytes")
    max_disk: Optional[int] = Field(None, description="Maximum disk size in bytes")
    uptime: Optional[int] = Field(None, description="Uptime in seconds")


class VMDetail(VMBase):
    """Detailed VM information."""
    cpu_count: Optional[int] = None
    os_type: Optional[str] = None
    template: Optional[str] = None
    boot: Optional[str] = None
    cores: Optional[int] = None
    sockets: Optional[int] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    lock: Optional[str] = None
    pid: Optional[int] = None


class NodeBase(BaseModel):
    """Base node information."""
    node: str
    status: str
    uptime: Optional[int] = None
    cpu: Optional[float] = None
    mem: Optional[int] = None
    max_mem: Optional[int] = None
    disk: Optional[int] = None
    max_disk: Optional[int] = None
    level: Optional[str] = None


class StorageBase(BaseModel):
    """Base storage information."""
    storage: str
    type: str
    status: str
    content: Optional[List[str]] = None
    total: Optional[int] = None
    used: Optional[int] = None
    available: Optional[int] = None
    enabled: bool = True


class ClusterStatus(BaseModel):
    """Cluster status information."""
    cluster_name: Optional[str] = None
    version: Optional[int] = None
    nodes: Optional[int] = None
    quorate: Optional[bool] = None
    status: Optional[str] = None


# ============================================================
# Health & Status Models
# ============================================================

class HealthResponse(BaseModel):
    status: str = Field(..., description="Health status (healthy, unhealthy)")
    timestamp: str = Field(..., description="ISO timestamp")
    version: str = Field(..., description="Server version")
    details: Optional[Dict[str, Any]] = None


class ReadinessResponse(BaseModel):
    ready: bool
    checks: Dict[str, bool] = Field(default_factory=dict)
    message: Optional[str] = None


class ErrorResponse(BaseModel):
    error: str
    code: str
    details: Optional[Dict[str, Any]] = None
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    request_id: Optional[str] = None


# ============================================================
# Audit Models
# ============================================================

class AuditLogEntry(BaseModel):
    timestamp: str
    event_type: str
    user: str
    ip_address: Optional[str] = None
    resource: Optional[str] = None
    operation: Optional[str] = None
    success: bool
    details: Optional[str] = None


# ============================================================
# Configuration Models
# ============================================================

class AllowedOperationsConfig(BaseModel):
    """Configuration for allowed operations."""
    operations: List[str] = Field(
        default=[
            "vm.list", "vm.status", "vm.start", "vm.stop", "vm.shutdown",
            "node.list", "node.status", "storage.list",
            "backup.list", "backup.status"
        ]
    )


class DeniedOperationsConfig(BaseModel):
    """Configuration for denied operations (blacklist)."""
    operations: List[str] = Field(
        default=[
            "vm.delete", "vm.destroy", "vm.remove",
            "node.stop", "node.reboot", "node.shutdown",
            "cluster.aclmodify", "user.modify"
        ]
    )


class RateLimitConfig(BaseModel):
    """Rate limiting configuration."""
    enabled: bool = True
    requests_per_minute: int = 60
    burst: int = 10


# ============================================================
# API Documentation Models
# ============================================================

class APIInfo(BaseModel):
    title: str = "Proxmox MCP Server"
    version: str = "1.0.0"
    description: str = "Secure MCP server for Proxmox VE management"
    documentation_url: Optional[str] = None


# ============================================================
# Validation Helpers
# ============================================================

def validate_vmid(vmid: int) -> bool:
    """Validate VM ID range (Proxmox uses 1-999999 for VMs, 100000+ for containers)."""
    return 1 <= vmid <= 999999


def validate_node_name(node: str) -> bool:
    """Validate Proxmox node name format."""
    import re
    # Node names should be valid hostname format
    pattern = r'^[a-zA-Z0-9][a-zA-Z0-9\-\.]*[a-zA-Z0-9]$'
    return bool(re.match(pattern, node)) and len(node) <= 255


__all__ = [
    # Enums
    "OperationRisk",
    "UserRole", 
    "VMStatus",
    # Auth
    "TokenRequest",
    "TokenResponse",
    "TokenIntrospectionResponse",
    # MCP
    "MCPRequest",
    "MCPResponse",
    "MCPOperationInfo",
    "MCPOperationListResponse",
    # Resources
    "VMBase",
    "VMDetail",
    "NodeBase",
    "StorageBase",
    "ClusterStatus",
    # Health
    "HealthResponse",
    "ReadinessResponse",
    "ErrorResponse",
    # Audit
    "AuditLogEntry",
    # Config
    "AllowedOperationsConfig",
    "DeniedOperationsConfig",
    "RateLimitConfig",
    "APIInfo",
    # Helpers
    "validate_vmid",
    "validate_node_name"
]