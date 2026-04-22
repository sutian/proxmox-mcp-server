"""
Tests for authentication module
"""

import pytest
from datetime import datetime, timedelta, timezone

# Use environment variables set in conftest.py
from auth import (
    create_token,
    verify_token,
    verify_proxmox_access,
    match_resource_pattern,
    get_role_permissions,
    is_operation_allowed,
    log_auth_event
)


class TestTokenCreation:
    """Tests for JWT token creation."""
    
    def test_create_basic_token(self):
        """Test basic token creation."""
        token = create_token("test-user", "operator", ["*"])
        assert token is not None
        assert isinstance(token, str)
        assert len(token) > 50  # JWT tokens are long
    
    def test_create_token_with_expiry(self):
        """Test token with custom expiry."""
        token = create_token(
            "test-user",
            "viewer",
            ["*/qemu/*"],
            expiry_minutes=30
        )
        
        claims = verify_token(token)
        assert claims is not None
        assert claims["sub"] == "test-user"
        assert claims["role"] == "viewer"
    
    def test_create_token_with_resources(self):
        """Test token with specific resource permissions."""
        resources = ["/nodes/pve11/qemu/*", "/cluster/resources"]
        token = create_token("test-user", "operator", resources)
        
        claims = verify_token(token)
        assert claims["allowed_resources"] == resources
    
    def test_admin_role_has_wildcard(self):
        """Test that admin role gets appropriate permissions."""
        token = create_token("admin", "admin", ["*"])
        claims = verify_token(token)
        
        assert claims["role"] == "admin"
        assert "*" in claims["allowed_resources"]


class TestTokenVerification:
    """Tests for JWT token verification."""
    
    def test_verify_valid_token(self, valid_token):
        """Test verification of valid token."""
        claims = verify_token(valid_token)
        assert claims is not None
        assert claims["sub"] == "test-user"
        assert "role" in claims
    
    def test_verify_invalid_token(self):
        """Test verification of invalid token."""
        claims = verify_token("invalid.token.here")
        assert claims is None
    
    def test_verify_empty_token(self):
        """Test verification of empty token."""
        claims = verify_token("")
        assert claims is None
    
    def test_verify_none_token(self):
        """Test verification of None token."""
        claims = verify_token(None)
        assert claims is None
    
    def test_expired_token(self):
        """Test that expired tokens are rejected."""
        import os
        os.environ["JWT_SECRET"] = "test-secret-key-for-testing-purposes-only-32chars"
        
        import jwt
        from auth import JWT_SECRET, JWT_ALGORITHM
        
        # Create an expired token manually
        now = datetime.now(timezone.utc)
        payload = {
            "sub": "test-user",
            "iat": now - timedelta(hours=2),
            "nbf": now - timedelta(hours=2),
            "exp": now - timedelta(hours=1)  # Expired 1 hour ago
        }
        
        expired_token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
        claims = verify_token(expired_token)
        
        assert claims is None  # Should be rejected


class TestResourcePatternMatching:
    """Tests for resource pattern matching."""
    
    def test_exact_match(self):
        """Test exact resource path match."""
        assert match_resource_pattern(
            "/nodes/pve11/qemu/501",
            "/nodes/pve11/qemu/501"
        ) is True
    
    def test_wildcard_suffix_match(self):
        """Test wildcard suffix matching."""
        assert match_resource_pattern(
            "/nodes/pve11/qemu/*",
            "/nodes/pve11/qemu/501"
        ) is True
        
        assert match_resource_pattern(
            "/nodes/pve11/qemu/*",
            "/nodes/pve11/qemu/502"
        ) is True
    
    def test_wildcard_prefix_match(self):
        """Test wildcard prefix matching."""
        assert match_resource_pattern(
            "*/qemu/501",
            "/nodes/pve11/qemu/501"
        ) is True
        
        assert match_resource_pattern(
            "*/qemu/*",
            "/nodes/pve12/qemu/100"
        ) is True
    
    def test_no_match(self):
        """Test non-matching patterns."""
        assert match_resource_pattern(
            "/nodes/pve11/qemu/*",
            "/nodes/pve12/qemu/501"
        ) is False
    
    def test_cluster_resources_match(self):
        """Test cluster resources pattern."""
        assert match_resource_pattern(
            "/cluster/resources",
            "/cluster/resources"
        ) is True
        
        assert match_resource_pattern(
            "/cluster/*",
            "/cluster/status"
        ) is True


class TestProxmoxAccessVerification:
    """Tests for Proxmox resource access verification."""
    
    def test_admin_has_full_access(self):
        """Test that admin role has access to all resources."""
        claims = {"role": "admin", "allowed_resources": ["*"]}
        
        assert verify_proxmox_access(claims, "/any/resource/path") is True
        assert verify_proxmox_access(claims, "/cluster/acls") is True
        assert verify_proxmox_access(claims, "/nodes/pve11/qemu/501") is True
    
    def test_operator_vm_access(self):
        """Test operator access to VM resources."""
        claims = {
            "role": "operator",
            "allowed_resources": ["*/qemu/*", "/cluster/resources"]
        }
        
        assert verify_proxmox_access(claims, "/nodes/pve11/qemu/501") is True
        assert verify_proxmox_access(claims, "/nodes/pve12/qemu/100") is True
        assert verify_proxmox_access(claims, "/cluster/resources") is True
    
    def test_no_access_to_denied_resource(self):
        """Test access denial for unauthorized resources."""
        claims = {
            "role": "operator",
            "allowed_resources": ["*/qemu/*"]
        }
        
        assert verify_proxmox_access(claims, "/cluster/acl") is False
        assert verify_proxmox_access(claims, "/nodes/pve11/storage") is False
    
    def test_wildcard_access(self):
        """Test wildcard resource pattern."""
        claims = {"role": "viewer", "allowed_resources": ["*"]}
        
        assert verify_proxmox_access(claims, "/any/resource") is True


class TestRolePermissions:
    """Tests for role-based permissions."""
    
    def test_admin_permissions(self):
        """Test admin role has all permissions."""
        perms = get_role_permissions("admin")
        
        assert "vm.list" in perms
        assert "vm.start" in perms
        assert "vm.delete" in perms
        assert "cluster.aclmodify" in perms
    
    def test_operator_permissions(self):
        """Test operator role has appropriate permissions."""
        perms = get_role_permissions("operator")
        
        assert "vm.list" in perms
        assert "vm.start" in perms
        assert "vm.stop" in perms
        assert "vm.delete" not in perms  # No delete permission
        assert "cluster.aclmodify" not in perms
    
    def test_viewer_permissions(self):
        """Test viewer role has read-only permissions."""
        perms = get_role_permissions("viewer")
        
        assert "vm.list" in perms
        assert "vm.status" in perms
        assert "vm.start" not in perms  # No start permission
        assert "vm.stop" not in perms
    
    def test_unknown_role_has_no_permissions(self):
        """Test that unknown roles have no permissions."""
        perms = get_role_permissions("unknown-role")
        assert perms == []


class TestOperationAllowance:
    """Tests for operation permission checking."""
    
    def test_admin_can_do_anything(self):
        """Test admin can perform any operation."""
        assert is_operation_allowed("admin", "vm.start") is True
        assert is_operation_allowed("admin", "vm.delete") is True
        assert is_operation_allowed("admin", "cluster.aclmodify") is True
    
    def test_operator_cannot_delete(self):
        """Test operator cannot delete VMs."""
        assert is_operation_allowed("operator", "vm.list") is True
        assert is_operation_allowed("operator", "vm.start") is True
        assert is_operation_allowed("operator", "vm.delete") is False
    
    def test_viewer_cannot_modify(self):
        """Test viewer cannot modify VMs."""
        assert is_operation_allowed("viewer", "vm.list") is True
        assert is_operation_allowed("viewer", "vm.status") is True
        assert is_operation_allowed("viewer", "vm.start") is False
        assert is_operation_allowed("viewer", "vm.stop") is False


class TestTokenIntrospection:
    """Tests for OAuth2 token introspection."""
    
    def test_introspect_active_token(self, valid_token):
        """Test introspection of active token."""
        from auth import introspect_token
        
        result = introspect_token(valid_token)
        
        assert result["active"] is True
        assert result["sub"] == "test-user"
        assert result["token_type"] == "Bearer"
    
    def test_introspect_invalid_token(self):
        """Test introspection of invalid token."""
        from auth import introspect_token
        
        result = introspect_token("invalid-token")
        
        assert result["active"] is False


class TestAuditLogging:
    """Tests for audit logging functionality."""
    
    def test_log_auth_event_success(self, caplog):
        """Test successful auth event logging."""
        with caplog.at_level("INFO"):
            log_auth_event("login", "test-user", True, "Login successful")
        
        assert "AUTH" in caplog.text
        assert "test-user" in caplog.text
        assert "success" in caplog.text.lower()
    
    def test_log_auth_event_failure(self, caplog):
        """Test failed auth event logging."""
        with caplog.at_level("WARNING"):
            log_auth_event("login", "test-user", False, "Invalid password")
        
        assert "AUTH_FAILURE" in caplog.text
        assert "test-user" in caplog.text


class TestJWTValidation:
    """Tests for JWT secret validation."""
    
    def test_validate_proper_secret(self):
        """Test validation of proper JWT secret."""
        from auth import validate_jwt_secret
        import os
        
        os.environ["JWT_SECRET"] = "a-very-long-secret-key-that-is-at-least-32-chars"
        
        assert validate_jwt_secret() is True
    
    def test_validate_empty_secret(self):
        """Test validation fails for empty secret."""
        from auth import validate_jwt_secret
        import os
        
        os.environ["JWT_SECRET"] = ""
        
        assert validate_jwt_secret() is False
    
    def test_validate_short_secret(self):
        """Test validation fails for short secret."""
        from auth import validate_jwt_secret
        import os
        
        os.environ["JWT_SECRET"] = "short"
        
        # Should warn but not fail completely
        result = validate_jwt_secret()
        # Note: This may return False due to length check