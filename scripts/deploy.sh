#!/bin/bash
# ============================================================
# Proxmox MCP Server - Deployment Script
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
IMAGE_NAME="proxmox-mcp"
IMAGE_TAG="${IMAGE_TAG:-latest}"
CONTAINER_NAME="proxmox-mcp"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# ============================================================
# Pre-deployment Checks
# ============================================================

check_docker() {
    if ! command -v docker &> /dev/null; then
        log_error "Docker is not installed. Please install Docker first."
        exit 1
    fi
    
    if ! docker info &> /dev/null; then
        log_error "Docker daemon is not running."
        exit 1
    fi
    
    log_info "Docker is available"
}

check_docker_compose() {
    if command -v docker-compose &> /dev/null; then
        DOCKER_COMPOSE="docker-compose"
    elif docker compose version &> /dev/null; then
        DOCKER_COMPOSE="docker compose"
    else
        log_error "Docker Compose is not installed."
        exit 1
    fi
    
    log_info "Docker Compose is available: $DOCKER_COMPOSE"
}

check_env_file() {
    if [ ! -f "$PROJECT_ROOT/.env" ]; then
        if [ -f "$PROJECT_ROOT/.env.example" ]; then
            log_warn ".env file not found. Copying from .env.example..."
            cp "$PROJECT_ROOT/.env.example" "$PROJECT_ROOT/.env"
            log_warn "Please edit .env and add your Proxmox credentials!"
        else
            log_error ".env file not found."
            exit 1
        fi
    fi
    
    # Validate required variables
    source "$PROJECT_ROOT/.env"
    
    REQUIRED_VARS=("PROXMOX_HOST" "PROXMOX_TOKEN_ID" "PROXMOX_TOKEN_SECRET" "JWT_SECRET")
    for var in "${REQUIRED_VARS[@]}"; do
        if [ -z "${!var}" ]; then
            log_error "Required environment variable $var is not set in .env"
            exit 1
        fi
    done
    
    # Validate JWT_SECRET length
    if [ ${#JWT_SECRET} -lt 32 ]; then
        log_error "JWT_SECRET must be at least 32 characters long"
        exit 1
    fi
    
    log_info "Environment configuration validated"
}

# ============================================================
# Build Image
# ============================================================

build_image() {
    log_info "Building Docker image: $IMAGE_NAME:$IMAGE_TAG"
    
    cd "$PROJECT_ROOT"
    
    docker build \
        -t "$IMAGE_NAME:$IMAGE_TAG" \
        -t "$IMAGE_NAME:latest" \
        --progress=plain \
        .
    
    log_info "Image built successfully"
}

# ============================================================
# Deploy
# ============================================================

deploy() {
    log_info "Deploying $CONTAINER_NAME..."
    
    cd "$PROJECT_ROOT"
    
    # Stop existing container if running
    if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        log_warn "Stopping existing container..."
        docker stop "$CONTAINER_NAME" || true
        docker rm "$CONTAINER_NAME" || true
    fi
    
    # Run docker-compose
    $DOCKER_COMPOSE up -d
    
    # Wait for container to be healthy
    log_info "Waiting for container to be healthy..."
    local retries=30
    while [ $retries -gt 0 ]; do
        if docker inspect --format='{{.State.Health.Status}}' "$CONTAINER_NAME" 2>/dev/null | grep -q "healthy"; then
            log_info "Container is healthy!"
            return 0
        fi
        
        # Also check if container is running at all
        if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
            log_info "Container is running..."
            return 0
        fi
        
        sleep 2
        retries=$((retries - 1))
        echo -n "."
    done
    
    echo ""
    log_warn "Health check did not complete, but container should be running"
}

# ============================================================
# Verify Deployment
# ============================================================

verify() {
    log_info "Verifying deployment..."
    
    # Check if container is running
    if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        log_error "Container is not running!"
        docker logs "$CONTAINER_NAME" --tail 50
        exit 1
    fi
    
    # Check health endpoint
    local host_port=$(docker port "$CONTAINER_NAME" 2>/dev/null | grep "8000" | cut -d':' -f2 || echo "8000")
    
    if command -v curl &> /dev/null; then
        local max_attempts=10
        local attempt=1
        
        while [ $attempt -le $max_attempts ]; do
            if curl -sf "http://localhost:${host_port}/health" > /dev/null 2>&1; then
                log_info "Health check passed!"
                return 0
            fi
            
            log_info "Health check attempt $attempt/$max_attempts..."
            sleep 2
            attempt=$((attempt + 1))
        done
        
        log_warn "Health endpoint not responding yet, but container is running"
    else
        log_warn "curl not available, skipping HTTP health check"
    fi
    
    # Show container status
    log_info "Container status:"
    docker ps --filter "name=$CONTAINER_NAME" --format "  {{.Names}}: {{.Status}}"
}

# ============================================================
# Show Logs
# ============================================================

show_logs() {
    log_info "Showing logs for $CONTAINER_NAME (Ctrl+C to exit):"
    
    docker logs -f "$CONTAINER_NAME"
}

# ============================================================
# Stop & Remove
# ============================================================

stop() {
    log_info "Stopping $CONTAINER_NAME..."
    
    cd "$PROJECT_ROOT"
    $DOCKER_COMPOSE down
    
    log_info "Container stopped and removed"
}

# ============================================================
# Restart
# ============================================================

restart() {
    log_info "Restarting $CONTAINER_NAME..."
    
    docker restart "$CONTAINER_NAME"
    
    log_info "Container restarted"
}

# ============================================================
# Shell Access
# ============================================================

shell() {
    log_info "Opening shell in $CONTAINER_NAME..."
    
    docker exec -it "$CONTAINER_NAME" /bin/sh
}

# ============================================================
# Main
# ============================================================

usage() {
    echo "Proxmox MCP Server Deployment Script"
    echo ""
    echo "Usage: $0 <command>"
    echo ""
    echo "Commands:"
    echo "  build     Build Docker image"
    echo "  deploy    Build and deploy the container"
    echo "  start     Start the container (if already built)"
    echo "  stop      Stop and remove the container"
    echo "  restart   Restart the container"
    echo "  logs      Show container logs (follow mode)"
    echo "  shell     Open shell in running container"
    echo "  verify    Verify deployment status"
    echo "  status    Show container status"
    echo "  clean     Remove container and image"
    echo "  help      Show this help message"
    echo ""
}

case "${1:-help}" in
    build)
        check_docker
        check_env_file
        build_image
        ;;
    deploy)
        check_docker
        check_docker_compose
        check_env_file
        build_image
        deploy
        verify
        ;;
    start)
        cd "$PROJECT_ROOT"
        $DOCKER_COMPOSE start
        ;;
    stop)
        cd "$PROJECT_ROOT"
        $DOCKER_COMPOSE stop
        ;;
    restart)
        restart
        ;;
    logs)
        show_logs
        ;;
    shell)
        shell
        ;;
    verify)
        verify
        ;;
    status)
        docker ps --filter "name=$CONTAINER_NAME" -a
        ;;
    clean)
        log_warn "This will remove the container and image!"
        read -p "Are you sure? (y/N) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            cd "$PROJECT_ROOT"
            $DOCKER_COMPOSE down --rmi all || true
            log_info "Clean complete"
        fi
        ;;
    help|--help|-h)
        usage
        ;;
    *)
        log_error "Unknown command: $1"
        usage
        exit 1
        ;;
esac