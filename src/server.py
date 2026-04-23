"""
Proxmox MCP Server - Main Application
"""

import os
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Any

from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pydantic_settings import BaseSettings

from auth import verify_token, verify_proxmox_access, create_token, log_auth_event as auth_log
from proxmox_client import ProxmoxClient

# Configuration
class Settings(BaseSettings):
    proxmox_host: str = os.getenv("PROXMOX_HOST", "")
    proxmox_port: int = int(os.getenv("PROXMOX_PORT", "8006"))
    proxmox_token_id: str = os.getenv("PROXMOX_TOKEN_ID", "")
    proxmox_token_secret: str = os.getenv("PROXMOX_TOKEN_SECRET", "")
    jwt_secret: str = os.getenv("JWT_SECRET", "")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    allowed_operations: str = os.getenv("ALLOWED_OPERATIONS",
        "vm.list,vm.status,vm.start,vm.stop,vm.shutdown,node.list,node.status,storage.list,backup.list,backup.status")

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()

# Logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("proxmox-mcp")

# FastAPI app
app = FastAPI(
    title="Proxmox MCP Server",
    description="Secure MCP server for Proxmox VE management",
    version="1.0.0"
)

# CORS - restricted to known origins (NEVER use "*" in production)
TRUSTED_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:8000",
    # Add your trusted frontend origins here
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

# Denied operations blacklist
DENIED_OPS = frozenset({
    "vm.delete", "vm.destroy", "vm.remove", "vm.create", "vm.modify", "vm.reset",
    "node.stop", "node.reboot", "node.shutdown",
    "cluster.aclmodify", "cluster.aclcreate", "cluster.acldelete",
    "user.modify", "user.delete", "user.create",
    "pool.modify", "pool.delete", "pool.create",
    "storage.modify", "storage.delete", "storage.create",
    "vzdump.restore", "vzdump.backup"
})

# Parse allowed operations
ALLOWED_OPS = frozenset(
    op.strip() for op in settings.allowed_operations.split(",")
    if op.strip()
)

logger.info(f"Allowed operations: {ALLOWED_OPS}")
logger.info(f"Denied operations: {DENIED_OPS}")

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
    logger.info(f"MCP call from user '{user_id}': method={request.method}")

    # Check DENIED_OPS blacklist (from denied_operations.json)
    denied_configured = frozenset({
        "vm.delete", "vm.destroy", "vm.remove", "vm.create", "vm.modify", "vm.reset",
        "node.stop", "node.reboot", "node.shutdown",
        "cluster.aclmodify", "cluster.aclcreate", "cluster.acldelete",
        "user.modify", "user.delete", "user.create",
        "pool.modify", "pool.delete", "pool.create",
        "storage.modify", "storage.delete", "storage.create",
        "vzdump.restore", "vzdump.backup"
    })

    if request.method in DENIED_OPS or request.method in denied_configured:
        logger.warning(f"Blocked denied operation: {request.method}")
        raise HTTPException(status_code=403, detail=f"Operation '{request.method}' is prohibited")

    if request.method not in ALLOWED_OPS:
        logger.warning(f"Operation not allowed: {request.method}")
        raise HTTPException(
            status_code=400,
            detail=f"Operation '{request.method}' not allowed. Allowed: {list(ALLOWED_OPS)}"
        )

    if not verify_proxmox_access(claims, request.resource):
        logger.warning(f"Access denied to resource '{request.resource}' for user '{user_id}'")
        raise HTTPException(status_code=403, detail="Access denied to this resource")

    try:
        client = ProxmoxClient(
            host=settings.proxmox_host,
            port=settings.proxmox_port,
            token_id=settings.proxmox_token_id,
            token_secret=settings.proxmox_token_secret,
            verify_tls=True
        )

        result = await client.execute(request.method, request.params)

        logger.info(f"Operation '{request.method}' completed successfully")

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
        "total_allowed": len(ALLOWED_OPS),
        "total_denied": len(DENIED_OPS)
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
        version="1.0.0"
    )

@app.get("/ready", tags=["Health"])
async def readiness_check():
    """Readiness check - verify Proxmox connectivity."""
    try:
        client = ProxmoxClient(
            host=settings.proxmox_host,
            port=settings.proxmox_port,
            token_id=settings.proxmox_token_id,
            token_secret=settings.proxmox_token_secret
        )
        await client.ping()
        return {"ready": True, "proxmox": "connected"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Proxmox not reachable: {str(e)}")

@app.get("/", tags=["Root"])
async def root():
    """Root endpoint with server info."""
    return {
        "service": "Proxmox MCP Server",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health"
    }

# ============================================================
# Authentication & RBAC Implementation (PRODUCTION: replace with LDAP/DB)
# ============================================================

# In-memory user store - REPLACE with real authentication in production!
# Users and passwords should be stored in LDAP, database, or OAuth2 provider
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
    logger.info(f"Configured Proxmox host: {settings.proxmox_host}")
    logger.info(f"Allowed operations: {len(ALLOWED_OPS)}")

    if not settings.jwt_secret:
        logger.error("JWT_SECRET not configured!")
    if not settings.proxmox_token_id:
        logger.error("PROXMOX_TOKEN_ID not configured!")
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
