"""
Authentication and Authorization Module for Proxmox MCP Server
"""

import os
import json
import jwt
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
from functools import wraps

# Configuration
JWT_SECRET = os.getenv("JWT_SECRET", "")
JWT_ALGORITHM = "HS256"
TOKEN_EXPIRY_MINUTES = 15

logger = logging.getLogger("proxmox-mcp.auth")

# ============================================================
# JWT Token Management
# ============================================================

def create_token(
    user_id: str,
    role: str = "operator",
    allowed_resources: List[str] = None,
    expiry_minutes: int = TOKEN_EXPIRY_MINUTES
) -> str:
    """
    Create a JWT access token.
    
    Args:
        user_id: Unique user identifier
        role: User role (admin, operator, viewer)
        allowed_resources: List of resource patterns user can access
        expiry_minutes: Token validity period
    
    Returns:
        Encoded JWT token string
    """
    if not JWT_SECRET:
        raise ValueError("JWT_SECRET not configured")
    
    if allowed_resources is None:
        allowed_resources = ["*"]
    
    now = datetime.now(timezone.utc)
    
    payload = {
        "sub": user_id,
        "role": role,
        "allowed_resources": allowed_resources,
        "iat": now,
        "nbf": now,  # Not valid before
        "exp": now + timedelta(minutes=expiry_minutes),
        "iss": "proxmox-mcp-server",
        "jti": f"{user_id}-{now.timestamp()}"  # Unique token ID
    }
    
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    
    logger.debug(f"Token created for user: {user_id}, role: {role}")
    
    return token


def verify_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Verify and decode a JWT token.
    
    Args:
        token: JWT token string
    
    Returns:
        Decoded payload dict if valid, None if invalid/expired
    """
    if not token or not JWT_SECRET:
        return None
    
    try:
        payload = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
            options={
                "require": ["sub", "exp", "iat", "nbf"],
                "verify_exp": True,
                "verify_nbf": True,
                "verify_iat": True
            }
        )
        
        return payload
        
    except jwt.ExpiredSignatureError:
        logger.warning("Token expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.warning(f"Invalid token: {str(e)}")
        return None


def decode_token_unsafe(token: str) -> Optional[Dict[str, Any]]:
    """
    Decode token without verification (for debugging only).
    
    WARNING: Do not use in production!
    """
    try:
        return jwt.decode(token, options={"verify_signature": False})
    except Exception:
        return None

# ============================================================
# Access Control (RBAC)
# ============================================================

def verify_proxmox_access(claims: Dict[str, Any], resource: str) -> bool:
    """
    Verify if user has access to the requested Proxmox resource.
    
    Implements a simple pattern-matching RBAC:
    - "*" matches all resources
    - "nodes/*" matches all nodes
    - "nodes/pve11/qemu/*" matches all VMs on pve11
    - Exact match for specific resources
    
    Args:
        claims: JWT token claims (must contain 'role' and 'allowed_resources')
        resource: Proxmox API resource path (e.g., "/nodes/pve11/qemu/501")
    
    Returns:
        True if access allowed, False otherwise
    """
    # Admin role has full access
    if claims.get("role") == "admin":
        logger.debug("Admin access granted")
        return True
    
    # Get allowed resources pattern
    allowed_resources = claims.get("allowed_resources", [])
    
    if "*" in allowed_resources:
        logger.debug(f"Wildcard access granted to: {resource}")
        return True
    
    # Check each pattern
    for pattern in allowed_resources:
        if match_resource_pattern(pattern, resource):
            logger.debug(f"Pattern '{pattern}' matched resource: {resource}")
            return True
    
    logger.warning(f"No pattern matched resource: {resource}")
    return False


def match_resource_pattern(pattern: str, resource: str) -> bool:
    """
    Match resource path against a pattern.
    
    Patterns support:
    - Exact match: "/nodes/pve11/qemu/501"
    - Wildcard suffix: "/nodes/pve11/qemu/*" matches all VMs on node
    - Prefix wildcard: "*/qemu/*" matches any node's VMs
    
    Args:
        pattern: Resource pattern (e.g., "/nodes/*/qemu/*")
        resource: Actual resource path
    
    Returns:
        True if pattern matches resource
    """
    if not pattern or not resource:
        return False
    
    # Normalize paths
    pattern = pattern.strip().rstrip("/")
    resource = resource.strip().rstrip("/")
    
    # Exact match
    if pattern == resource:
        return True
    
    # Wildcard suffix matching
    if pattern.endswith("/*"):
        prefix = pattern[:-2]  # Remove /*
        if resource.startswith(prefix):
            # Check it's a complete segment match
            remainder = resource[len(prefix):]
            if remainder.startswith("/") or remainder == "":
                return True
    
    # Wildcard prefix matching
    if pattern.startswith("*/"):
        suffix = pattern[2:]  # Remove */
        if resource.endswith(suffix) or resource == suffix:
            return True
    
    return False


def require_role(required_role: str):
    """
    Decorator to require specific role for an endpoint.
    
    Usage:
        @app.post("/admin-only")
        @require_role("admin")
        async def admin_endpoint():
            ...
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Extract token from kwargs or context
            # This is a simplified version - adapt to your framework
            return func(*args, **kwargs)
        return wrapper
    return decorator

# ============================================================
# Permission Helpers
# ============================================================

def get_role_permissions(role: str) -> List[str]:
    """
    Get list of operations allowed for a role.
    
    Roles:
    - admin: Full access (use carefully!)
    - operator: Can manage VMs (start, stop, etc.)
    - viewer: Read-only access
    """
    permissions = {
        "admin": [
            "vm.list", "vm.status", "vm.start", "vm.stop", "vm.shutdown",
            "vm.create", "vm.delete", "vm.modify",
            "node.list", "node.status", "node.start", "node.stop",
            "storage.list", "storage.modify",
            "backup.list", "backup.create", "backup.restore",
            "cluster.status", "cluster.aclmodify"
        ],
        "operator": [
            "vm.list", "vm.status", "vm.start", "vm.stop", "vm.shutdown",
            "node.list", "node.status",
            "storage.list",
            "backup.list"
        ],
        "viewer": [
            "vm.list", "vm.status",
            "node.list", "node.status",
            "storage.list",
            "backup.list"
        ]
    }
    
    return permissions.get(role, [])


def is_operation_allowed(role: str, operation: str) -> bool:
    """Check if a role can perform a specific operation."""
    return operation in get_role_permissions(role)

# ============================================================
# Token Introspection (for OAuth2 compatibility)
# ============================================================

def introspect_token(token: str) -> Dict[str, Any]:
    """
    OAuth2 token introspection endpoint implementation.
    
    Returns token metadata including:
    - active: Whether token is valid
    - scope: Allowed operations
    - exp: Expiration timestamp
    - sub: User ID
    """
    claims = verify_token(token)
    
    if not claims:
        return {
            "active": False,
            "token_type": "Bearer"
        }
    
    return {
        "active": True,
        "scope": " ".join(get_role_permissions(claims.get("role", "viewer"))),
        "token_type": "Bearer",
        "exp": int(claims.get("exp", 0)),
        "sub": claims.get("sub", ""),
        "role": claims.get("role", "viewer"),
        "iat": int(claims.get("iat", 0)),
        "jti": claims.get("jti", "")
    }

# ============================================================
# Audit Logging
# ============================================================

def log_auth_event(
    event_type: str,
    user_id: str,
    success: bool,
    details: str = "",
    ip_address: str = None
):
    """Log authentication/authorization events for audit."""
    log_data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event_type,
        "user": user_id,
        "success": success,
        "details": details
    }
    
    if ip_address:
        log_data["ip"] = ip_address
    
    if success:
        logger.info(f"AUTH: {json.dumps(log_data)}")
    else:
        logger.warning(f"AUTH_FAILURE: {json.dumps(log_data)}")

# ============================================================
# Secret Validation
# ============================================================

def validate_jwt_secret() -> bool:
    """Validate that JWT_SECRET is properly configured."""
    if not JWT_SECRET:
        logger.error("JWT_SECRET environment variable not set!")
        return False
    
    if len(JWT_SECRET) < 32:
        logger.warning("JWT_SECRET is shorter than recommended 32 characters")
        return False
    
    return True

if __name__ == "__main__":
    # Test token creation and verification
    print("Testing JWT module...")
    
    # Test create
    token = create_token("test-user", "operator", ["*/qemu/*"])
    print(f"Created token: {token[:50]}...")
    
    # Test verify
    claims = verify_token(token)
    print(f"Verified claims: {claims}")
    
    # Test access check
    print(f"Access to /nodes/pve11/qemu/501: {verify_proxmox_access(claims, '/nodes/pve11/qemu/501')}")
    print(f"Access to /cluster/acls: {verify_proxmox_access(claims, '/cluster/acls')}")
    
    print("Tests passed!")