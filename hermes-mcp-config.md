# Hermes MCP Client Configuration for OpenClaw
# =============================================
#
# This file configures how Hermes (OpenClaw agent) connects to the
# Proxmox MCP server to manage Proxmox VE resources via Telegram.
#
# SETUP INSTRUCTIONS:
# -------------------
# 1. Deploy proxmox-mcp-server on a VM (e.g., 192.168.1.27:8000)
# 2. Set environment variables (see .env.example)
# 3. Get JWT token from /auth/token endpoint
# 4. Add MCP server to OpenClaw config
#
# For OpenClaw MCP configuration, edit:
#   ~/.openclaw/agents/main/config.json  (or similar)
#
# Example OpenClaw MCP config format:
# {
#   "mcpServers": {
#     "proxmox": {
#       "url": "http://192.168.1.27:8000/mcp/v1",
#       "headers": {
#         "Authorization": "Bearer <YOUR_JWT_TOKEN>"
#       }
#     }
#   }
# }
#
# Or use SSE streaming for real-time responses:
# {
#   "mcpServers": {
#     "proxmox": {
#       "url": "http://192.168.1.27:8000/mcp/v1/stream",
#       "headers": {
#         "Authorization": "Bearer <YOUR_JWT_TOKEN>"
#       },
#       "transport": "sse"
#     }
#   }
# }

# ============================================================
# Environment Variables for proxmox-mcp-server
# ============================================================
#
# Copy this to .env and configure:
#
# PROXMOX_HOST=192.168.1.11        # Proxmox node IP
# PROXMOX_PORT=8006
# PROXMOX_TOKEN_ID=root@pam!api-token-pve11
# PROXMOX_TOKEN_SECRET=<your-token>
# JWT_SECRET=<32+ char secret>
# ADMIN_PASSWORD=<admin-password>
# OPERATOR_PASSWORD=<operator-password>
# VIEWER_PASSWORD=<viewer-password>

# ============================================================
# API Usage Examples
# ============================================================
#
# 1. Get JWT Token:
#    POST http://192.168.1.27:8000/auth/token
#    Body: {"username": "admin", "password": "YOUR_PASSWORD"}
#
# 2. List VMs:
#    POST http://192.168.1.27:8000/mcp/v1/call
#    Headers: {"Authorization": "Bearer <TOKEN>"}
#    Body: {"method": "vm.list", "params": {}}
#
# 3. Start VM:
#    POST http://192.168.1.27:8000/mcp/v1/call
#    Headers: {"Authorization": "Bearer <TOKEN>"}
#    Body: {"method": "vm.start", "params": {"node": "pve13", "vmid": 2701}}
#
# 4. Clone VM (admin only):
#    POST http://192.168.1.27:8000/mcp/v1/call
#    Headers: {"Authorization": "Bearer <TOKEN>"}
#    Body: {"method": "vm.clone", "params": {"node": "pve13", "vmid": 2404, "newid": 2702}}

# ============================================================
# Telegram -> Hermes -> MCP Server -> Proxmox Flow
# ============================================================
#
# User (Telegram)
#      │
#      ▼
# Hermes Agent (OpenClaw)
#      │  (MCP tool calls)
#      ▼
# proxmox-mcp-server (192.168.1.27:8000)
#      │  (REST API + JWT auth)
#      ▼
# Proxmox VE API (192.168.1.11:8006)
#
# Available Operations:
# - vm.list, vm.status, vm.start, vm.stop, vm.shutdown (all users)
# - vm.create, vm.clone (admin only)
# - node.list, node.status (all users)
# - storage.list (all users)
# - backup.list, backup.status (all users)
