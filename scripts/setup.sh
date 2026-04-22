#!/bin/bash
# ============================================================
# Proxmox MCP Server - Setup Script
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║       Proxmox MCP Server - Setup & Configuration           ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# Check prerequisites
check_prerequisites() {
    echo "[1/5] Checking prerequisites..."
    
    if ! command -v docker &> /dev/null; then
        echo "ERROR: Docker is not installed."
        exit 1
    fi
    
    if ! docker info &> /dev/null; then
        echo "ERROR: Docker daemon is not running."
        exit 1
    fi
    
    echo "✓ Docker is available"
}

# Generate secure secrets
generate_secrets() {
    echo ""
    echo "[2/5] Generating secure secrets..."
    
    # Generate JWT_SECRET if not set
    if [ -z "$JWT_SECRET" ]; then
        export JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
        echo "✓ JWT_SECRET generated"
    else
        echo "✓ JWT_SECRET already set"
    fi
}

# Setup Proxmox API token
setup_proxmox_token() {
    echo ""
    echo "[3/5] Proxmox API Token Setup"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "You need a Proxmox API token to connect securely."
    echo ""
    echo "Run these commands on your Proxmox node:"
    echo ""
    echo "  # Create dedicated user for MCP"
    echo "  pveum user add mcp-service@pve"
    echo ""
    echo "  # Create custom role (read-only + power operations)"
    echo "  pveum role add MCP-Operator -privs \\"
    echo "    VM.Audit VM.PowerVM VM.Read Datastore.Audit Sys.Audit"
    echo ""
    echo "  # Create API token"
    echo "  pveum token add mcp-service@pve mcp-token"
    echo ""
    echo "  # Grant permissions"
    echo "  pveum aclmod / -user mcp-service@pve -role MCP-Operator"
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    
    read -p "Enter Proxmox host IP or FQDN: " PROXMOX_HOST
    read -p "Enter Token ID (format: user@realm!tokenname): " PROXMOX_TOKEN_ID
    read -p "Enter Token Secret: " PROXMOX_TOKEN_SECRET
    
    export PROXMOX_HOST
    export PROXMOX_TOKEN_ID
    export PROXMOX_TOKEN_SECRET
}

# Create .env file
create_env_file() {
    echo ""
    echo "[4/5] Creating .env file..."
    
    cat > "$PROJECT_ROOT/.env" << EOF
# Proxmox Connection
PROXMOX_HOST=${PROXMOX_HOST}
PROXMOX_PORT=8006

# API Token (from Proxmox user creation)
PROXMOX_TOKEN_ID=${PROXMOX_TOKEN_ID}
PROXMOX_TOKEN_SECRET=${PROXMOX_TOKEN_SECRET}

# JWT Authentication
JWT_SECRET=${JWT_SECRET}

# Allowed Operations
ALLOWED_OPERATIONS=vm.list,vm.status,vm.start,vm.stop,vm.shutdown,node.list,node.status,storage.list,backup.list,backup.status

# Logging
LOG_LEVEL=INFO
EOF
    
    echo "✓ .env file created"
}

# Test configuration
test_configuration() {
    echo ""
    echo "[5/5] Testing configuration..."
    
    # Source the env file
    source "$PROJECT_ROOT/.env"
    
    echo "  Proxmox Host: $PROXMOX_HOST"
    echo "  Token ID: $PROXMOX_TOKEN_ID"
    echo "  JWT Secret: ${#JWT_SECRET} characters"
    
    echo ""
    echo "✓ Configuration complete!"
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "Next steps:"
    echo "  1. Review .env file: nano .env"
    echo "  2. Build image: ./scripts/deploy.sh build"
    echo "  3. Deploy: ./scripts/deploy.sh deploy"
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

# Main
check_prerequisites
generate_secrets
setup_proxmox_token
create_env_file
test_configuration