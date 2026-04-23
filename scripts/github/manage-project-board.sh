#!/usr/bin/env bash
#===============================================================================
# GitHub Project Board + Milestone Management Script
# Repo: sutian/proxmox-mcp-server
# 
# Usage:
#   ./scripts/github/manage-project-board.sh setup    # Create board + milestones
#   ./scripts/github/manage-project-board.sh sync    # Sync issues to board
#   ./scripts/github/manage-project-board.sh add-milestone <title> <desc>
#
# Prerequisites:
#   - gh authenticated: gh auth login
#   - Or set GITHUB_TOKEN env var
#===============================================================================

set -euo pipefail

REPO="sutian/proxmox-mcp-server"
OWNER="sutian"
PROJECT_NAME="proxmox-mcp-server Roadmap"

#-------------------------------------------------------------------------------
# Helpers
#-------------------------------------------------------------------------------
require_auth() {
  if ! gh auth status &>/dev/null; then
    echo "ERROR: Not authenticated. Run 'gh auth login' first." >&2
    exit 1
  fi
}

api() {
  gh api "$@"
}

#-------------------------------------------------------------------------------
# Setup: Create project board + milestones
#-------------------------------------------------------------------------------
setup() {
  require_auth
  echo "=== Setting up GitHub Project Board + Milestones ==="

  # --- Milestones ---
  local milestones=(
    "v0.1.0:MVP - Basic MCP server with VM lifecycle ops"
    "v0.2.0:Enhanced error handling + Proxmox auth"
    "v0.3.0:Storage + backup management"
    "v1.0.0:Production-ready release"
  )

  echo ""
  echo "--- Creating Milestones ---"
  for ms in "${milestones[@]}"; do
    local title="${ms%%:*}"
    local desc="${ms##*:}"
    local existing
    existing=$(api "repos/$REPO/milestones?state=open" 2>/dev/null | \
      grep -o "\"title\": \"$title\"" | head -1 || true)
    if [[ -n "$existing" ]]; then
      echo "  [SKIP] Milestone '$title' already exists"
    else
      api "repos/$REPO/milestones" --method POST \
        -f title="$title" -f description="$desc" -f state="open" 2>/dev/null
      echo "  [CREATED] Milestone: $title"
    fi
  done

  # --- Project Board (v2) ---
  echo ""
  echo "--- Creating Project Board ---"
  
  # Get user node_id
  local user_node
  user_node=$(api graphql -f query='{ viewer { id } }' 2>/dev/null | \
    grep -o '"id": "[^"]*"' | head -1 | sed 's/"id": "//;s/"//') || true
  
  if [[ -z "$user_node" ]]; then
    echo "  [SKIP] Could not resolve user ID for project creation"
    echo "  Note: Project v2 creation requires 'project' scope in token."
    echo "  Existing milestones are ready to use."
    return
  fi

  # Try GraphQL project creation
  local project_result
  project_result=$(api graphql -f query="
    mutation {
      createProjectV2(input: {ownerId: \"$user_node\", title: \"$PROJECT_NAME\"}) {
        projectV2 {
          id
          title
          url
        }
      }
    }" 2>&1) || true

  if echo "$project_result" | grep -q '"id"'; then
    local project_id project_url
    project_id=$(echo "$project_result" | grep -o '"id": "[^"]*"' | head -1 | sed 's/"id": "//;s/"//')
    project_url=$(echo "$project_result" | grep -o '"url": "[^"]*"' | head -1 | sed 's/"url": "//;s/"//')
    echo "  [CREATED] Project: $PROJECT_NAME ($project_url)"
  else
    echo "  [SKIP] Project creation failed: token may lack 'project' scope"
    echo "  Milestones created successfully — can be used without a board."
  fi

  echo ""
  echo "=== Setup Complete ==="
  echo "Milestones: https://github.com/$REPO/milestones"
  echo "Project:    https://github.com/users/$OWNER/projects"
}

#-------------------------------------------------------------------------------
# Sync: Show current state
#-------------------------------------------------------------------------------
sync() {
  require_auth
  echo "=== Syncing Project State ==="
  
  echo ""
  echo "--- Milestones ---"
  api "repos/$REPO/milestones?state=all" 2>/dev/null | \
    grep -oE '"number": [0-9]+|"title": "[^"]+"|"state": "[^"]+' | \
    sed 's/"//g' | paste - - - | column -t || \
    echo "  No milestones found"

  echo ""
  echo "--- Open Issues ---"
  api "repos/$REPO/issues?state=open&labels=" 2>/dev/null | \
    grep -oE '"number": [0-9]+|"title": "[^"]+' | \
    head -20 | sed 's/"//g' | paste - - || \
    echo "  No open issues"
}

#-------------------------------------------------------------------------------
# Add milestone manually
#-------------------------------------------------------------------------------
add_milestone() {
  local title="${1:-}"
  local desc="${2:-}"
  require_auth
  if [[ -z "$title" ]]; then
    echo "Usage: $0 add-milestone <title> [description]" >&2
    exit 1
  fi
  api "repos/$REPO/milestones" --method POST \
    -f title="$title" -f description="$desc" -f state="open" 2>/dev/null
  echo "Created milestone: $title"
}

#-------------------------------------------------------------------------------
# Main
#-------------------------------------------------------------------------------
COMMAND="${1:-}"
case "$COMMAND" in
  setup)  setup ;;
  sync)   sync ;;
  add-milestone) add_milestone "${2:-}" "${3:-}" ;;
  *)
    echo "Usage: $0 {setup|sync|add-milestone <title> [desc]}"
    exit 1
    ;;
esac
