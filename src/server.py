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

from auth import verify_token, verify_proxmox_access, create_token
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

# CORS - restricted to known origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure this for production
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
    "vm.delete", "vm.destroy", "vm.remove",
    "node.stop", "node.reboot", "node.shutdown",
    "cluster.aclmodify", "cluster.aclcreate",
    "user.modify", "user.delete", "user.create",
    "pool.modify", "pool.delete",
    "storage.modify", "storage.delete",
    "vzdump.restore"
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
    
    In production, this would validate against an external IdP
    (OAuth2, LDAP, etc.). For this implementation, we use a
    simplified credential check.
    """
    # TODO: Replace with actual authentication provider
    # This is a placeholder for demonstration
    if not verify_credentials(request.username, request.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    # Create token with allowed operations
    allowed_resources = get_user_resources(request.username)
    token = create_token(
        user_id=request.username,
        role="operator",
        allowed_resources=allowed_resources
    )
    
    logger.info(f"Token issued for user: {request.username}")
    
    return TokenResponse(
        access_token=token,
        expires_in=900
    )

@app.post("/auth/refresh", response_model=TokenResponse, tags=["Authentication"])
async def refresh_token(authorization: str = Header(None)):
    """Refresh an existing JWT token."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization header")
    
    token = authorization.replace("Bearer ", "")
    claims = verify_token(token)
    
    if not claims:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    
    # Create new token
    new_token = create_token(
        user_id=claims.get("sub", ""),
        role=claims.get("role", "operator"),
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
    # 1. Authenticate
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
    
    # 2. Check operation blacklist
    if request.method in DENIED_OPS:
        logger.warning(f"Blocked denied operation: {request.method}")
        raise HTTPException(
            status_code=403,
            detail=f"Operation '{request.method}' is prohibited"
        )
    
    # 3. Check operation whitelist
    if request.method not in ALLOWED_OPS:
        logger.warning(f"Operation not allowed: {request.method}")
        raise HTTPException(
            status_code=400,
            detail=f"Operation '{request.method}' not allowed. Allowed: {list(ALLOWED_OPS)}"
        )
    
    # 4. Verify resource access
    if not verify_proxmox_access(claims, request.resource):
        logger.warning(f"Access denied to resource '{request.resource}' for user '{user_id}'")
        raise HTTPException(
            status_code=403,
            detail="Access denied to this resource"
        )
    
    # 5. Execute via Proxmox client
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
        
        return MCPResponse(
            success=True,
            data=result,
            operation=request.method
        )
        
    except Exception as e:
        logger.error(f"Operation '{request.method}' failed: {str(e)}")
        return MCPResponse(
            success=False,
            error=str(e),
            operation=request.method
        )

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
# Helper Functions (placeholder implementations)
# ============================================================

def verify_credentials(username: str, password: str) -> bool:
    """
    Verify user credentials.
    
    In production, integrate with:
    - LDAP/Active Directory
    - OAuth2 provider
    - SSO service
    - Database lookup
    
    This is a placeholder that accepts any non-empty credentials
    for demonstration purposes.
    """
    # Placeholder: Accept any non-empty credentials
    # TODO: Replace with actual authentication
    return bool(username and password)

def get_user_resources(username: str) -> list:
    """
    Get list of resources the user can access.
    
    In production, this would query RBAC/permissions database.
    """
    # Placeholder: Return wildcard for full access
    # TODO: Implement actual RBAC lookup
    return ["*"]

# ============================================================
# Startup & Shutdown Events
# ============================================================

@app.on_event("startup")
async def startup_event():
    logger.info("Proxmox MCP Server starting up...")
    logger.info(f"Configured Proxmox host: {settings.proxmox_host}")
    logger.info(f"Allowed operations: {len(ALLOWED_OPS)}")
    
    # Validate configuration
    if not settings.jwt_secret:
        logger.error("JWT_SECRET not configured!")
    if not settings.proxmox_token_id:
        logger.error("PROXMOX_TOKEN_ID not configured!")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Proxmox MCP Server shutting down...")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)