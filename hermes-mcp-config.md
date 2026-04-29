# Hermes MCP Client Configuration for Proxmox MCP Server
# =========================================================
#
# This file configures how Hermes (Telegram agent) connects to the
# Proxmox MCP server to manage Proxmox VE infrastructure via Telegram.
#
# SETUP INSTRUCTIONS:
# -------------------
# 1. Deploy proxmox-mcp-server (see README.md)
# 2. Set environment variables (see .env.example)
# 3. Get JWT token from /auth/token endpoint
# 4. Add MCP server to Hermes config
#
# For Hermes MCP configuration, edit:
#   ~/.hermes/config.yaml
#
# Example Hermes MCP config format:
# mcpServers:
#   proxmox:
#     url: http://192.168.1.9:8000/mcp/v1
#     headers:
#       Authorization: "Bearer <YOUR_JWT_TOKEN>"

# ============================================================
# Environment Variables for proxmox-mcp-server
# ============================================================
#
# Copy this to .env and configure:
#
# --- Single Node ---
# PROXMOX_HOST=192.168.1.11
# PROXMOX_PORT=8006
# PROXMOX_TOKEN_ID=root@pam!api-token
# PROXMOX_TOKEN_SECRET=<your-token>
#
# --- Multi-Host / Cluster ---
# Format: node_name:host:port,node_name:host:port
# PROXMOX_NODES=pve11:192.168.1.11:8006,pve12:192.168.1.12:8006,pve13:192.168.1.13:8006
#
# Per-node token overrides (if different nodes use different tokens):
# PROXMOX_NODE_TOKENS=pve11=root@pam!token1:secret1,pve12=root@pam!token2:secret2
#
# --- Auth & Security ---
# JWT_SECRET=<32+ char secret>
# ADMIN_PASSWORD=<admin-password>
# OPERATOR_PASSWORD=<operator-password>
# VIEWER_PASSWORD=<viewer-password>
# VERIFY_TLS=false  # set true for production with real certs

# ============================================================
# API Usage Examples
# ============================================================

# 1. Get JWT Token
curl -s -X POST http://localhost:8000/auth/token \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "YOUR_PASSWORD"}'

# 2. Discover Cluster Members (auto-discovers all cluster nodes)
curl -s http://localhost:8000/mcp/v1/cluster/members \
  -H "Authorization: Bearer <TOKEN>"

# 3. List All VMs Across Cluster (cluster-wide, no node needed)
curl -s -X POST http://localhost:8000/mcp/v1/call \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"method":"cluster.resources","resource":"*","params":{"type":"vm"}}'

# 4. List VMs on Specific Node
curl -s -X POST http://localhost:8000/mcp/v1/call \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"method":"vm.list","resource":"*/qemu/*","params":{"node":"pve11"}}'

# 5. Start VM
curl -s -X POST http://localhost:8000/mcp/v1/call \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"method":"vm.start","resource":"/nodes/pve11/qemu/501","params":{"node":"pve11","vmid":501}}'

# 6. Stop VM
curl -s -X POST http://localhost:8000/mcp/v1/call \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"method":"vm.stop","resource":"/nodes/pve11/qemu/501","params":{"node":"pve11","vmid":501}}'

# 7. Migrate VM (live migrate to another node)
curl -s -X POST http://localhost:8000/mcp/v1/call \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"method":"vm.migrate","resource":"/nodes/pve11/qemu/501","params":{"node":"pve11","vmid":501,"target":"pve12"}}'

# 8. Clone VM (admin only)
curl -s -X POST http://localhost:8000/mcp/v1/call \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"method":"vm.clone","resource":"/nodes/pve13/qemu/2404","params":{"node":"pve13","vmid":2404,"newid":2702}}'

# 9. List Cluster Status
curl -s -X POST http://localhost:8000/mcp/v1/call \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"method":"cluster.status","resource":"*","params":{}}'

# 10. List Storage
curl -s -X POST http://localhost:8000/mcp/v1/call \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"method":"storage.list","resource":"*","params":{}}'

# 11. List Available Operations
curl -s http://localhost:8000/mcp/v1/operations \
  -H "Authorization: Bearer <TOKEN>"

# ============================================================
# Available Operations
# ============================================================

# Cluster-wide operations (no node param needed):
#   cluster.members   - discover all cluster nodes
#   cluster.resources - all VMs/storage across cluster
#   cluster.status    - HA cluster status
#   cluster.config    - cluster configuration
#   storage.list      - all storage backends
#   backup.list       - all backup jobs

# Node-specific operations (node param required):
#   vm.list, vm.status, vm.start, vm.stop, vm.shutdown
#   vm.create, vm.clone, vm.migrate (admin only)
#   node.list, node.status

# ============================================================
# Telegram -> Hermes -> MCP Server -> Proxmox Flow
# ============================================================

# User (Telegram)
#      │
#      ▼
# Hermes Agent
#      │  (MCP tool calls)
#      ▼
# proxmox-mcp-server (192.168.1.9:8000)
#      │  (REST API + JWT auth)
#      ▼
# Proxmox VE API (cluster nodes)

# ============================================================
# Resource Patterns (for access control)
# ============================================================

# Patterns supported in JWT allowed_resources:
#   "*"                 - all resources (admin)
#   "*/qemu/*"          - all VMs on any node
#   "*/node/*"          - all node info
#   "/nodes/pve11/qemu/*" - all VMs on specific node
#   "/cluster/*"        - cluster-wide resources
