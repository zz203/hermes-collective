#!/usr/bin/env bash
# ────────────────────────────────────────────────────────────────
# Hermes Collective — One-command install
# ────────────────────────────────────────────────────────────────
#
# Usage:
#   bash setup.sh
#
# This script installs the hermes-collective package.
# After install, run:  hermes-collective setup
# That interactive wizard handles Profile creation, repo setup, and skills.
# ────────────────────────────────────────────────────────────────

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()  { echo -e "${GREEN}[✓]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
err()   { echo -e "${RED}[✗]${NC} $*"; }

echo -e "${BLUE}"
echo "╔══════════════════════════════════════════╗"
echo "║     Hermes Collective — Install          ║"
echo "╚══════════════════════════════════════════╝"
echo -e "${NC}"

# ── 1. Check Hermes ──────────────────────────────────────────

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"

if ! command -v hermes &>/dev/null; then
    err "Hermes Agent not found. Install it first:"
    echo "   curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash"
    exit 1
fi
info "Hermes Agent: $(hermes --version 2>/dev/null || echo 'installed')"

# ── 2. Install hermes-collective ─────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

info "Installing hermes-collective..."
pip install -e "$SCRIPT_DIR" --quiet 2>&1 | tail -1

if command -v hermes-collective &>/dev/null; then
    info "CLI ready: $(hermes-collective --version)"
else
    err "CLI not found on PATH."
    exit 1
fi

# ── 3. Install skills ────────────────────────────────────────

SKILLS_SRC="$SCRIPT_DIR/hermes_collective/skills"
SKILLS_DST="$HERMES_HOME/skills/collective"

if [ -d "$SKILLS_SRC" ]; then
    mkdir -p "$SKILLS_DST"
    for skill_dir in "$SKILLS_SRC"/*/; do
        skill_name=$(basename "$skill_dir")
        if [ -f "$skill_dir/SKILL.md" ]; then
            mkdir -p "$SKILLS_DST/$skill_name"
            cp "$skill_dir/SKILL.md" "$SKILLS_DST/$skill_name/SKILL.md"
            info "  Skill: $skill_name"
        fi
    done
fi

# ── 4. Next steps ────────────────────────────────────────────

echo ""
echo -e "${GREEN}Install complete!${NC}"
echo ""
echo -e "${BLUE}Next: run the interactive setup wizard${NC}"
echo ""
echo "  hermes-collective setup"
echo ""
echo "This will guide you through:"
echo "  → Choose role (employee or manager)"
echo "  → Enter agent name and repo URL"
echo "  → Auto-create Hermes Profile"
echo "  → Auto-clone repo and register identity"
echo "  → Print cron setup commands"
echo ""
