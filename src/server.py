"""
Proxmox MCP Server - Main Application
"""

import os
import re
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Any

from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pydantic_settings import BaseSettings

from .auth import verify_token, verify_proxmox_access, create_token, log_auth_event as auth_log
from .proxmox_client import ProxmoxClient

# ============================================================
# Input Validation Helpers (High Priority Fix)
# ============================================================

class ValidationError(Exception):
    """Raised when parameter validation fails."""
    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message
        super().__init__(f"[{field}] {message}")


def validate_operation_params(method: str, params: dict) -> dict:
    """
    Validate and sanitize operation parameters before sending to Proxmox API.

    Raises ValidationError if params are invalid.
    Returns sanitized params dict.

    # Validated fields:
    # - vmid: must be integer in range 1-999999
    # - node: must be valid hostname format
    # - storage: alphanumeric + dash/underscore, max 64 chars
    # - Other string params: stripped, length limits
    """
    if not params:
        return {}

    sanitized = {}
    errors = []

    for key, value in params.items():
        if value is None:
            continue

        # ---- vmid: must be positive integer within Proxmox range ----
        if key == "vmid":
            try:
                vmid = int(value)
                if not (1 <= vmid <= 999999):
                    errors.append(f"vmid must be 1-999999, got {vmid}")
                else:
                    sanitized[key] = vmid
            except (TypeError, ValueError):
                errors.append(f"vmid must be integer, got {type(value).__name__}: {repr(value)}")

        # ---- node: valid hostname format ----
        elif key == "node":
            if not isinstance(value, str):
                errors.append(f"node must be string, got {type(value).__name__}")
            elif not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9\-\.]*[a-zA-Z0-9]$', value):
                errors.append(f"node name '{value}' contains invalid characters")
            elif len(value) > 255:
                errors.append(f"node name exceeds 255 characters")
            else:
                sanitized[key] = value.strip()

        # ---- storage: safe identifier ----
        elif key == "storage":
            if not isinstance(value, str):
                errors.append(f"storage must be string, got {type(value).__name__}")
            elif not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9_\-]*$', value):
                errors.append(f"storage name '{value}' contains invalid characters")
            elif len(value) > 64:
                errors.append(f"storage name exceeds 64 characters")
            else:
                sanitized[key] = value.strip()

        # ---- name/vmname: general string sanitization ----
        elif key in ("name", "vmname", "new_name", "clone"):
            if not isinstance(value, str):
                errors.append(f"{key} must be string, got {type(value).__name__}")
            elif len(value) > 255:
                errors.append(f"{key} exceeds 255 characters")
            else:
                sanitized[key] = value.strip()

        # ---- numeric string params (memory, cpu, etc.) ----
        elif key in ("memory", "cores", "sockets", "cpu", "disk", "size"):
            try:
                sanitized[key] = int(value)
            except (TypeError, ValueError):
                errors.append(f"{key} must be integer, got {repr(value)}")

        # ---- passthrough unknown fields after basic sanitization ----
        elif isinstance(value, (str, int, float, bool, list, dict)):
            sanitized[key] = value

        # ---- silently skip anything else (None, bytes, etc.) ----
        # prevent type-confusion attacks

    if errors:
        raise ValidationError("params", "; ".join(errors))

    return sanitized

# ============================================================
# Configuration - Multi-Host Support
# ============================================================

class NodeConfig(BaseModel):
    """Configuration for a single Proxmox node."""
    name: str
    host: str
    port: int = 8006

def parse_proxmox_nodes(nodes_str: str) -> dict:
    """
    Parse PROXMOX_NODES into dict of NodeConfig.

    Format: node_name:host:port,node_name:host:port
    Example: pve11:192.168.1.11:8006,pve12:192.168.1.12:8006

    Port defaults to 8006 if not specified.
    """
    if not nodes_str:
        return {}

    nodes = {}
    for entry in nodes_str.split(","):
        entry = entry.strip()
        if not entry:
            continue

        parts = entry.split(":")
        if len(parts) == 2:
            name, host = parts
            port = 8006
        elif len(parts) == 3:
            name, host, port = parts
            port = int(port)
        else:
            logger.warning(f"Invalid node entry ignored: {entry}")
            continue

        nodes[name] = NodeConfig(name=name, host=host, port=port)
        logger.info(f"Parsed node '{name}' -> {host}:{port}")

    return nodes

class Settings(BaseSettings):
    # Multi-host: comma-separated node configs (node:host:port)
    proxmox_nodes: str = os.getenv("PROXMOX_NODES", "")

    # Legacy single-host (for backward compatibility)
    proxmox_host: str = os.getenv("PROXMOX_HOST", "")
    proxmox_port: int = int(os.getenv("PROXMOX_PORT", "8006"))

    # Shared token (used if per-node token not set)
    proxmox_token_id: str = os.getenv("PROXMOX_TOKEN_ID", "")
    proxmox_token_secret: str = os.getenv("PROXMOX_TOKEN_SECRET", "")

    # Per-node token overrides (optional): node_name=token_id:token_secret,...
    proxmox_node_tokens: str = os.getenv("PROXMOX_NODE_TOKENS", "")

    jwt_secret: str = os.getenv("JWT_SECRET", "")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    verify_tls: bool = os.getenv("VERIFY_TLS", "true").lower() == "true"
    allowed_operations: str = os.getenv("ALLOWED_OPERATIONS",
        "vm.list,vm.status,vm.start,vm.stop,vm.shutdown,vm.create,vm.clone,node.list,node.status,storage.list,backup.list,backup.status")

    class Config:
        env_file = ".env"
        extra = "ignore"


# ============================================================
# Early logger init (parse_proxmox_nodes uses logger before settings = Settings())
# ============================================================
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("proxmox-mcp")

settings = Settings()

# ---- SECURITY WARNING: warn if TLS verification is disabled ----
if not settings.verify_tls:
    logger.warning(
        "VERIFY_TLS=false: SSL/TLS certificate verification is DISABLED. "
        "This is insecure for production and exposes the server to man-in-the-middle attacks. "
        "Only use for local dev with self-signed certificates."
    )

# ============================================================
# Node Registry - Build client per node
# ============================================================

def build_node_registry() -> dict:
    """
    Build a registry of Proxmox clients, one per node.

    Resolution order for credentials:
    1. Per-node token override (PROXMOX_NODE_TOKENS)
    2. Shared token (PROXMOX_TOKEN_ID/SECRET)
    """
    registry = {}

    # Parse multi-host config
    if settings.proxmox_nodes:
        node_configs = parse_proxmox_nodes(settings.proxmox_nodes)
    elif settings.proxmox_host:
        # Fallback to legacy single-host
        node_configs = {"default": NodeConfig(name="default", host=settings.proxmox_host, port=settings.proxmox_port)}
    else:
        logger.warning("No Proxmox nodes configured (PROXMOX_NODES or PROXMOX_HOST)")
        node_configs = {}

    # Parse per-node token overrides
    node_token_overrides = {}
    if settings.proxmox_node_tokens:
        for entry in settings.proxmox_node_tokens.split(","):
            entry = entry.strip()
            if not entry or "=" not in entry:
                continue
            node_name, token_pair = entry.split("=", 1)
            if ":" in token_pair:
                token_id, token_secret = token_pair.split(":", 1)
                node_token_overrides[node_name.strip()] = {
                    "token_id": token_id.strip(),
                    "token_secret": token_secret.strip()
                }

    # Build client for each node
    for node_name, node_config in node_configs.items():
        if node_name in node_token_overrides:
            token_id = node_token_overrides[node_name]["token_id"]
            token_secret = node_token_overrides[node_name]["token_secret"]
        else:
            token_id = settings.proxmox_token_id
            token_secret = settings.proxmox_token_secret

        registry[node_name] = {
            "config": node_config,
            "client": ProxmoxClient(
                host=node_config.host,
                port=node_config.port,
                token_id=token_id,
                token_secret=token_secret,
                verify_tls=settings.verify_tls
            )
        }
        logger.info(f"Registered node '{node_name}' -> {node_config.host}:{node_config.port}")

    return registry

# Global registry
NODE_REGISTRY = build_node_registry()
AVAILABLE_NODES = list(NODE_REGISTRY.keys())

# Logging (update level from settings after settings is available)
logging.getLogger("proxmox-mcp").setLevel(getattr(logging, settings.log_level.upper()))

# FastAPI app
app = FastAPI(
    title="Proxmox MCP Server",
    description="Secure MCP server for Proxmox VE management (Multi-Host)",
    version="1.1.0"
)

# CORS - restricted to known origins (NEVER use "*" in production)
TRUSTED_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:8000",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=TRUSTED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

# Pydantic models
class TokenRequest(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 900  # 15 minutes

class MCPRequest(BaseModel):
    method: str
    params: dict = {}
    resource: str = "/"

class MCPResponse(BaseModel):
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None
    operation: Optional[str] = None

class HealthResponse(BaseModel):
    status: str
    timestamp: str
    version: str
    nodes: list[str] = []

# Denied operations blacklist (always blocked)
DENIED_OPS = frozenset({
    "vm.delete", "vm.destroy", "vm.remove",
    "node.stop", "node.reboot", "node.shutdown",
    "cluster.aclmodify", "cluster.aclcreate", "cluster.acldelete",
    "user.modify", "user.delete", "user.create",
    "pool.modify", "pool.delete", "pool.create",
    "storage.modify", "storage.delete", "storage.create",
    "vzdump.restore", "vzdump.backup"
})

# Admin-only operations (allowed but requires admin role)
ADMIN_ONLY_OPS = frozenset({
    "vm.create", "vm.clone", "vm.modify", "vm.reset",
})

# Parse allowed operations
ALLOWED_OPS = frozenset(
    op.strip() for op in settings.allowed_operations.split(",")
    if op.strip()
)

logger.info(f"Allowed operations: {ALLOWED_OPS}")
logger.info(f"Denied operations: {DENIED_OPS}")
logger.info(f"Admin-only operations: {ADMIN_ONLY_OPS}")

# ============================================================
# Authentication Endpoints
# ============================================================

@app.post("/auth/token", response_model=TokenResponse, tags=["Authentication"])
async def get_token(request: TokenRequest):
    """
    Get JWT access token.
    Requires username (3+ chars) and password (8+ chars).
    In production, replace _USER_DB with LDAP/OAuth2/DB lookup.
    """
    if not verify_credentials(request.username, request.password):
        auth_log("token_request", request.username, False, "Invalid credentials")
        raise HTTPException(status_code=401, detail="Invalid credentials")

    allowed_resources = get_user_resources(request.username)
    token = create_token(
        user_id=request.username,
        role=get_user_role(request.username),
        allowed_resources=allowed_resources
    )

    auth_log("token_request", request.username, True, "Token issued")
    logger.info(f"Token issued for user: {request.username}")

    return TokenResponse(access_token=token, expires_in=900)

@app.post("/auth/refresh", response_model=TokenResponse, tags=["Authentication"])
async def refresh_token(authorization: str = Header(None)):
    """Refresh an existing JWT token."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization header")

    token = authorization.replace("Bearer ", "")
    claims = verify_token(token)

    if not claims:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    new_token = create_token(
        user_id=claims.get("sub", ""),
        role=claims.get("role", "viewer"),
        allowed_resources=claims.get("allowed_resources", [])
    )

    return TokenResponse(access_token=new_token, expires_in=900)

# ============================================================
# MCP Operations Endpoints
# ============================================================

@app.post("/mcp/v1/call", response_model=MCPResponse, tags=["MCP"])
async def mcp_call(
    request: MCPRequest,
    authorization: str = Header(None)
):
    """
    Execute an MCP operation against Proxmox.
    Requires valid JWT token in Authorization header.
    """
    if not authorization:
        logger.warning("Missing authorization header")
        raise HTTPException(status_code=401, detail="Missing authorization header")

    token = authorization.replace("Bearer ", "")
    claims = verify_token(token)

    if not claims:
        logger.warning("Invalid or expired token")
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user_id = claims.get("sub", "unknown")
    user_role = claims.get("role", "viewer")
    logger.info(f"MCP call from user '{user_id}' (role={user_role}): method={request.method}")

    # 1. Check DENIED_OPS blacklist
    if request.method in DENIED_OPS:
        logger.warning(f"Blocked denied operation: {request.method}")
        raise HTTPException(status_code=403, detail=f"Operation '{request.method}' is prohibited")

    # 2. Check operation whitelist
    if request.method not in ALLOWED_OPS:
        logger.warning(f"Operation not allowed: {request.method}")
        raise HTTPException(
            status_code=400,
            detail=f"Operation '{request.method}' not allowed. Allowed: {list(ALLOWED_OPS)}"
        )

    # 3. Check admin-only operations
    if request.method in ADMIN_ONLY_OPS and user_role != "admin":
        logger.warning(f"Admin-only operation '{request.method}' blocked for role '{user_role}'")
        raise HTTPException(status_code=403, detail=f"Operation '{request.method}' requires admin role")

    # 4. Verify resource access
    if not verify_proxmox_access(claims, request.resource):
        logger.warning(f"Access denied to resource '{request.resource}' for user '{user_id}'")
        raise HTTPException(status_code=403, detail="Access denied to this resource")

    # 5. Determine target node (resolve from params.node)
    target_node = request.params.get("node") if request.params else None
    if not target_node:
        if AVAILABLE_NODES:
            target_node = AVAILABLE_NODES[0]
            logger.debug(f"No target node specified, defaulting to '{target_node}'")
        else:
            raise HTTPException(status_code=503, detail="No Proxmox nodes configured")
    elif target_node not in NODE_REGISTRY:
        raise HTTPException(status_code=400, detail=f"Unknown node '{target_node}'. Available: {AVAILABLE_NODES}")

    # 6. Validate & sanitize params before sending to Proxmox
    try:
        params = validate_operation_params(request.method, request.params)
    except ValidationError as ve:
        logger.warning(f"Parameter validation failed for '{request.method}': {ve}")
        raise HTTPException(status_code=400, detail=str(ve))

    # 7. Execute via Proxmox client for the target node
    try:
        node_entry = NODE_REGISTRY[target_node]
        client = node_entry["client"]
        result = await client.execute(request.method, params)

        logger.info(f"Operation '{request.method}' on node '{target_node}' completed successfully")

        return MCPResponse(success=True, data=result, operation=request.method)

    except Exception as e:
        logger.error(f"Operation '{request.method}' failed: {str(e)}")
        return MCPResponse(success=False, error=str(e), operation=request.method)

@app.get("/mcp/v1/operations", tags=["MCP"])
async def list_operations(authorization: str = Header(None)):
    """List all available MCP operations."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization header")

    token = authorization.replace("Bearer ", "")
    claims = verify_token(token)

    if not claims:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return {
        "allowed": sorted(list(ALLOWED_OPS)),
        "denied": sorted(list(DENIED_OPS)),
        "admin_only": sorted(list(ADMIN_ONLY_OPS)),
        "total_allowed": len(ALLOWED_OPS),
        "total_denied": len(DENIED_OPS),
        "total_admin_only": len(ADMIN_ONLY_OPS)
    }

@app.get("/mcp/v1/nodes", tags=["MCP"])
async def list_nodes():
    """List all available Proxmox nodes and their connection status."""
    node_status = []
    for node_name, node_entry in NODE_REGISTRY.items():
        config = node_entry["config"]
        status = "unknown"
        try:
            await node_entry["client"].ping()
            status = "connected"
        except Exception as e:
            status = f"error: {str(e)[:50]}"

        node_status.append({
            "name": node_name,
            "host": config.host,
            "port": config.port,
            "status": status
        })

    return {
        "nodes": node_status,
        "total": len(node_status)
    }

# ============================================================
# Health & Status Endpoints
# ============================================================

@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """Health check endpoint for monitoring."""
    return HealthResponse(
        status="healthy",
        timestamp=datetime.utcnow().isoformat(),
        version="1.1.0",
        nodes=AVAILABLE_NODES
    )

@app.get("/ready", tags=["Health"])
async def readiness_check():
    """Readiness check - verify Proxmox connectivity for all nodes."""
    results = {}
    for node_name, node_entry in NODE_REGISTRY.items():
        try:
            client = node_entry["client"]
            await client.ping()
            results[node_name] = "connected"
        except Exception as e:
            results[node_name] = f"error: {str(e)[:50]}"

    all_connected = all("connected" in s for s in results.values())
    if all_connected:
        return {"ready": True, "nodes": results}
    raise HTTPException(status_code=503, detail=f"Proxmox nodes not fully reachable: {results}")

@app.get("/", tags=["Root"])
async def root():
    """Root endpoint with server info."""
    return {
        "service": "Proxmox MCP Server",
        "version": "1.1.0",
        "docs": "/docs",
        "health": "/health",
        "nodes": AVAILABLE_NODES
    }

# ============================================================
# Authentication & RBAC Implementation
# PRODUCTION: Replace _USER_DB with LDAP/OAuth2/DB
# ============================================================

# In-memory user store
# Set passwords via environment variables:
#   ADMIN_PASSWORD, OPERATOR_PASSWORD, VIEWER_PASSWORD
_USER_DB = {
    "admin":    {"password": os.getenv("ADMIN_PASSWORD", ""),    "role": "admin",    "resources": ["*"]},
    "operator": {"password": os.getenv("OPERATOR_PASSWORD", ""), "role": "operator", "resources": ["*/qemu/*", "*/node/*", "*/storage/*"]},
    "viewer":   {"password": os.getenv("VIEWER_PASSWORD", ""),   "role": "viewer",   "resources": ["*/qemu/list", "*/node/list"]},
}


def verify_credentials(username: str, password: str) -> bool:
    """
    Verify user credentials.
    REPLACE this with real authentication (LDAP, OAuth2, database).
    """
    if not username or len(username) < 3:
        return False
    if not password or len(password) < 8:
        return False

    user = _USER_DB.get(username.lower())
    if not user:
        logger.warning(f"Login attempt for unknown user: {username}")
        return False

    stored_password = user.get("password", "")
    if not stored_password or stored_password in ("", "REPLACE_WITH_STRONG_PASSWORD"):
        logger.warning(f"Login attempt with unset password for user: {username}")
        return False

    return password == stored_password


def get_user_resources(username: str) -> list:
    """Get list of resources the user can access. REPLACE with real RBAC lookup."""
    user = _USER_DB.get(username.lower())
    if user:
        return user.get("resources", [])
    logger.warning(f"User '{username}' not found - denying all resources")
    return []


def get_user_role(username: str) -> str:
    """Get role for user from RBAC system. REPLACE with real lookup."""
    user = _USER_DB.get(username.lower())
    return user.get("role", "viewer") if user else "viewer"


# ============================================================
# Startup & Shutdown Events
# ============================================================

@app.on_event("startup")
async def startup_event():
    logger.info("Proxmox MCP Server starting up...")
    logger.info(f"Version: 1.1.0 (Multi-Host Support)")
    logger.info(f"Available nodes: {AVAILABLE_NODES}")
    logger.info(f"Allowed operations: {len(ALLOWED_OPS)}")
    
    if not settings.jwt_secret:
        logger.error("JWT_SECRET not configured!")
    if not settings.proxmox_token_id and not settings.proxmox_node_tokens:
        logger.error("No Proxmox token configured (PROXMOX_TOKEN_ID or PROXMOX_NODE_TOKENS)")
    if len(settings.jwt_secret) < 32:
        logger.warning("JWT_SECRET is shorter than recommended 32 characters")

    # Warn if using default/replace passwords
    for username, user_data in _USER_DB.items():
        pwd = user_data.get("password", "")
        if pwd in ("", "REPLACE_WITH_STRONG_PASSWORD"):
            logger.warning(f"User '{username}' has a placeholder password - MUST change in production!")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Proxmox MCP Server shutting down...")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
