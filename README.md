# Proxmox MCP Server

A secure Model Context Protocol (MCP) server for managing Proxmox VE infrastructure via Docker with multi-host support.

## Features

- 🔐 JWT-based authentication with short-lived tokens
- 🛡️ RBAC with operation whitelist/blacklist
- 🔒 TLS encrypted communication with Proxmox API
- 📦 Docker deployment with security hardening
- 📝 Audit logging for all operations
- 🌐 **Multi-Host Support** - Manage multiple Proxmox nodes from a single server

## Quick Start

### 1. Prerequisites

- Docker & Docker Compose
- Proxmox VE 7.x or 8.x
- Python 3.12+ (for local development)

### 2. Create Proxmox API Token

On each Proxmox node:

```bash
# Create dedicated user
pveum user add mcp-service@pve

# Create custom role (principle of least privilege)
pveum role add MCP-Operator -privs \
  VM.Audit \
  VM.PowerVM \
  VM.Read \
  Datastore.Audit \
  Sys.Audit

# Create token for each node
pveum token add mcp-service@pve mcp-token --privsep 0

# Grant role to user
pveum aclmod / -user mcp-service@pve -role MCP-Operator
```

Save the token values:
- `token_id`: `mcp-service@pve!mcp-token`
- `token_secret`: `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`

### 3. Configuration

```bash
# Copy environment template
cp .env.example .env

# Edit with your values
nano .env
```

#### Cluster Features

For Proxmox clusters, the server supports automatic node discovery and cluster-wide operations:

```bash
# GET /mcp/v1/cluster/members — auto-discover all cluster nodes
curl http://localhost:8000/mcp/v1/cluster/members \
  -H "Authorization: Bearer $TOKEN"
# Returns all cluster members with status (no need to configure each node manually)
```

Cluster-wide operations (no `--node` flag needed):
- `cluster.resources` — all VMs/storage across cluster
- `cluster.members` — discover cluster nodes
- `cluster.status` — HA cluster status
- `cluster.config` — cluster configuration
- `storage.list` — all storage backends
- `backup.list` — all backup jobs

#### Per-Node Configuration

```bash
# Format: node_name:host:port,node_name:host:port
PROXMOX_NODES=pve11:192.168.1.11:8006,pve12:192.168.1.12:8006,pve13:192.168.1.13:8006

# Per-node token overrides (node_name=token_id:token_secret,...)
# If not specified, falls back to PROXMOX_TOKEN_ID/SECRET
PROXMOX_NODE_TOKENS=pve11:root@pam!api-token-pve11:xxxxxxxx,pve12:root@pam!api-token-pve12:xxxxxxxx,pve13:root@pam!api-token-pve13:xxxxxxxx
```

Required environment variables:

| Variable | Description |
|----------|-------------|
| `PROXMOX_NODES` | Multi-host config (node:host:port,...) |
| `PROXMOX_TOKEN_ID` | API token ID (fallback if per-node not set) |
| `PROXMOX_TOKEN_SECRET` | API token secret (fallback if per-node not set) |
| `PROXMOX_NODE_TOKENS` | Per-node token overrides |
| `JWT_SECRET` | JWT signing secret (min 32 chars) |
| `ADMIN_PASSWORD` | Password for admin user |
| `VERIFY_TLS` | Verify TLS certs (default: false for self-signed) |

### 4. Deploy

```bash
# Build and start
docker-compose up -d --build

# Check logs
docker-compose logs -f

# Verify health
curl http://localhost:8000/health
```

### 5. Connect Client

Example request:

```bash
# Get JWT token
TOKEN=$(curl -s -X POST http://localhost:8000/auth/token \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"P@ssw0rd"}' | \
  python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')

# List VMs on specific node
curl -X POST http://localhost:8000/mcp/v1/call \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"method":"vm.list","params":{"node":"pve11"},"resource":"*/qemu/*"}'
```

## Security Features

### Network Isolation
- Container runs in isolated network (`mcp-network`)
- No ports exposed to host by default
- Use nginx reverse proxy for TLS if external access needed

### Container Hardening
- **Non-root user**: Runs as user ID 1000
- **Read-only filesystem**: No writes to container layers
- **No new privileges**: `security_opt: no-new-privileges`
- **Capability drop**: All Linux capabilities removed
- **Resource limits**: Max 256MB RAM, 0.5 CPU

### Authentication Flow

```
Client                    MCP Server                Proxmox
   │                           │                        │
   │──── JWT Token ───────────▶│                        │
   │                           │                        │
   │                           │──── API Request ──────▶│
   │                           │                        │
   │                           │◀─── Response ─────────│
   │                           │                        │
   │◀─── Result ──────────────│                        │
```

1. Client authenticates via `/auth/token` endpoint
2. Client receives short-lived JWT (15 min)
3. Client calls MCP endpoint with JWT
4. MCP validates token, checks RBAC
5. MCP proxies request to Proxmox API

## API Reference

### Authentication

```bash
# Get access token
curl -X POST http://localhost:8000/auth/token \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "P@ssw0rd"}'

# Refresh token
curl -X POST http://localhost:8000/auth/refresh \
  -H "Authorization: Bearer <expired_token>"
```

### MCP Operations

All operations require `Authorization: Bearer <jwt>` header.

```bash
# List VMs on specific node (params.node is required for multi-host)
curl -X POST http://localhost:8000/mcp/v1/call \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "method": "vm.list",
    "params": {"node": "pve11"},
    "resource": "*/qemu/*"
  }'

# Get VM status
curl -X POST http://localhost:8000/mcp/v1/call \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "method": "vm.status",
    "params": {"node": "pve11", "vmid": "501"},
    "resource": "*/qemu/*"
  }'

# Start VM
curl -X POST http://localhost:8000/mcp/v1/call \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "method": "vm.start",
    "params": {"node": "pve11", "vmid": "501"},
    "resource": "*/qemu/*"
  }'

# Get VM snapshots
curl -X POST http://localhost:8000/mcp/v1/call \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "method": "vm.snapshot",
    "params": {"node": "pve11", "vmid": "501"},
    "resource": "*/qemu/*"
  }'

# Node status
curl -X POST http://localhost:8000/mcp/v1/call \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "method": "node.status",
    "params": {"node": "pve11"},
    "resource": "*/node/*"
  }'
```

### Allowed Operations

| Operation | Description | Risk Level |
|-----------|-------------|------------|
| `vm.list` | List all VMs on a node | Low |
| `vm.status` | Get VM status | Low |
| `vm.snapshot` | List VM snapshots | Low |
| `vm.start` | Start a VM | Medium |
| `vm.stop` | Stop a VM (hard) | Medium |
| `vm.shutdown` | Graceful shutdown | Medium |
| `vm.create` | Create VM (admin only) | High |
| `vm.clone` | Clone VM (admin only) | High |
| `node.list` | List cluster nodes | Low |
| `node.status` | Get node status | Low |
| `storage.list` | List storage | Low |
| `backup.list` | List backups | Low |
| `backup.status` | Get backup status | Low |

### Denied Operations (Blacklist)

These operations are always blocked regardless of role:

- `vm.delete` / `vm.destroy`
- `node.stop` / `node.reboot` / `node.shutdown`
- `cluster.*` (all cluster operations)
- `user.*` (all user operations)
- `storage.*` (modify/delete)
- `pool.*` (all pool operations)
- `vzdump.restore` / `vzdump.backup`

## Multi-Host Usage

When `PROXMOX_NODES` is configured, specify the target node in `params.node`:

```bash
# pve11
curl ... -d '{"method":"vm.list","params":{"node":"pve11"},...}'

# pve12
curl ... -d '{"method":"vm.list","params":{"node":"pve12"},...}'

# pve13
curl ... -d '{"method":"vm.list","params":{"node":"pve13"},...}'
```

If `node` is omitted, defaults to the first node in `PROXMOX_NODES`.

## Development

### Local Setup

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run with env file
export $(cat .env | xargs) && uvicorn src.server:app --reload --port 8000
```

### Run Tests

```bash
pytest tests/ -v --cov=src

# With coverage report
pytest tests/ -v --cov=src --cov-report=html
open htmlcov/index.html
```

### Docker Build

```bash
# Build image
docker build -t proxmox-mcp:latest .

# Run with environment file
docker run --env-file .env proxmox-mcp:latest

# Interactive test
docker run -it --env-file .env proxmox-mcp:latest python -m pytest
```

## Deployment Guide

### Production Deployment

#### 1. Firewall Configuration

```bash
# Allow only from internal network
ufw allow from 192.168.1.0/24 to any port 8000

# Or disable external access entirely
ufw deny 8000
```

#### 2. TLS Termination (Optional)

For external access, use nginx with self-signed cert:

```bash
# Generate certificate
openssl req -x509 -nodes -days 365 \
  -newkey rsa:2048 \
  -keyout certs/key.pem \
  -out certs/cert.pem \
  -subj "/CN=proxmox-mcp"
```

#### 3. Reverse Proxy (nginx.conf)

```nginx
events {
    worker_connections 1024;
}

http {
    server {
        listen 8443 ssl;
        server_name _;

        ssl_certificate /certs/cert.pem;
        ssl_certificate_key /certs/key.pem;

        location / {
            proxy_pass http://proxmox-mcp:8000;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }
    }
}
```

#### 4. Health Monitoring

```bash
# Add to crontab for health check
*/5 * * * * curl -f http://localhost:8000/health || \
  docker-compose restart proxmox-mcp
```

### Kubernetes Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: proxmox-mcp
spec:
  replicas: 1
  selector:
    matchLabels:
      app: proxmox-mcp
  template:
    metadata:
      labels:
        app: proxmox-mcp
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        fsGroup: 1000
      containers:
      - name: proxmox-mcp
        image: proxmox-mcp:latest
        securityContext:
          readOnlyRootFilesystem: true
          allowPrivilegeEscalation: false
        resources:
          limits:
            memory: 256Mi
            cpu: "0.5"
        envFrom:
        - secretRef:
            name: proxmox-secrets
```

## Troubleshooting

### Common Issues

**401 Unauthorized**
- Check JWT token hasn't expired (15 min default)
- Verify token signature matches JWT_SECRET
- Ensure `params.node` is specified for multi-host setup

**403 Forbidden**
- Operation may be blacklisted
- User may not have permission for requested resource
- Some operations (vm.create, vm.clone) require admin role

**Connection to Proxmox failed**
- Verify `PROXMOX_NODES` is correctly formatted
- Check each node's API port (8006) is accessible
- Ensure API tokens are valid for each node

**Certificate verify failed**
- Set `VERIFY_TLS=false` for self-signed certs (default)
- For production, add CA bundle or use valid certs

**Unknown node errors**
- Verify node name matches exactly (case-sensitive)
- Check `PROXMOX_NODES` format: `name:host:port,name:host:port`
- Ensure node is reachable from container

### Debug Mode

```bash
# Enable debug logging
sed -i 's/LOG_LEVEL=.*/LOG_LEVEL=DEBUG/' .env
docker-compose restart

# View verbose logs
docker-compose logs -f --tail=100
```

### Container Shell

```bash
# Debug inside container
docker exec -it proxmox-mcp /bin/sh

# Check Python environment
docker exec proxmox-mcp python -c "import sys; print(sys.version)"

# Test Proxmox connectivity directly
docker exec proxmox-mcp python -c "
from src.proxmox_client import ProxmoxClient
import asyncio
async def test():
    client = ProxmoxClient(host='192.168.1.11', port=8006,
                          token_id='root@pam!token', token_secret='xxx',
                          verify_tls=False)
    result = await client.ping()
    print('Ping:', result)
asyncio.run(test())
"
```

## License

MIT

## Author

OxTigger - Proxmox MCP Server v1.1.0
