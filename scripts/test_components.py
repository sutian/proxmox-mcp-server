"""
Quick test script to verify MCP server components
"""

import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from auth import create_token, verify_token, verify_proxmox_access
from proxmox_client import ProxmoxClient, OPERATION_ENDPOINTS
from models import MCPRequest, validate_vmid, validate_node_name

def test_auth():
    print("Testing authentication module...")
    
    # Create token
    token = create_token("test-user", "operator", ["*/qemu/*", "/cluster/*"])
    print(f"  ✓ Created token: {token[:50]}...")
    
    # Verify token
    claims = verify_token(token)
    assert claims is not None, "Token verification failed"
    print(f"  ✓ Verified token for user: {claims['sub']}")
    print(f"  ✓ Role: {claims['role']}")
    
    # Test access
    assert verify_proxmox_access(claims, "/nodes/pve11/qemu/501") == True
    print(f"  ✓ Access control works")
    
    return True

def test_proxmox_client():
    print("\nTesting Proxmox client...")
    
    client = ProxmoxClient(
        host="192.168.1.11",
        token_id="test@pam!token",
        token_secret="secret"
    )
    
    print(f"  ✓ Client initialized: {client.base_url}")
    print(f"  ✓ {len(OPERATION_ENDPOINTS)} operations defined")
    
    # Test endpoint mapping
    assert "vm.list" in OPERATION_ENDPOINTS
    assert "vm.start" in OPERATION_ENDPOINTS
    print(f"  ✓ Operation endpoints configured")
    
    return True

def test_models():
    print("\nTesting Pydantic models...")
    
    # Test MCPRequest
    request = MCPRequest(
        method="vm.list",
        params={"type": "vm"},
        resource="/cluster/resources"
    )
    print(f"  ✓ MCPRequest valid: {request.method}")
    
    # Test validation
    assert validate_vmid(501) == True
    assert validate_vmid(0) == False
    print(f"  ✓ VM ID validation works")
    
    assert validate_node_name("pve11") == True
    assert validate_node_name("invalid name") == False
    print(f"  ✓ Node name validation works")
    
    return True

def main():
    print("=" * 60)
    print("Proxmox MCP Server - Component Tests")
    print("=" * 60)
    
    tests = [
        ("Auth Module", test_auth),
        ("Proxmox Client", test_proxmox_client),
        ("Models", test_models),
    ]
    
    all_passed = True
    for name, test_func in tests:
        try:
            if test_func():
                print(f"✓ {name}: PASSED")
        except Exception as e:
            print(f"✗ {name}: FAILED - {e}")
            all_passed = False
    
    print("\n" + "=" * 60)
    if all_passed:
        print("All tests PASSED!")
        return 0
    else:
        print("Some tests FAILED!")
        return 1

if __name__ == "__main__":
    sys.exit(main())