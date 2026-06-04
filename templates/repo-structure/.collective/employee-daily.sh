# Employee Daily Cron Script
# Triggered by Hermes cron job at 18:00 Mon-Fri
# Loads the employee-daily skill and runs the daily report workflow.

set -euo pipefail

COLLECTIVE="${COLLECTIVE_PATH:-$HOME/.hermes/collective}"
AGENT_NAME="${AGENT_NAME:-unknown}"
REPO_URL="${REPO_URL:-}"

echo "=== Employee Daily Report ==="
echo "Agent: $AGENT_NAME"
echo "Collective: $COLLECTIVE"
echo "Date: $(date +%Y-%m-%d)"
echo ""

# Pull latest collective state
cd "$COLLECTIVE"
git pull --ff-only origin main

# Sync active skills to local Hermes
echo "Syncing skills from collective..."
mkdir -p ~/.hermes/skills/collective/
for skill_dir in skills/active/*/; do
    if [ -f "$skill_dir/SKILL.md" ]; then
        skill_name=$(basename "$skill_dir")
        mkdir -p ~/.hermes/skills/collective/"$skill_name"
        cp "$skill_dir/SKILL.md" ~/.hermes/skills/collective/"$skill_name/SKILL.md"
        echo "  ✓ $skill_name"
    fi
done

echo ""
echo "Skills synced. Hermes will now load the employee-daily workflow."
echo "Run: hermes chat -s collective/employee-daily -q 'Daily report for $AGENT_NAME. Collective: $COLLECTIVE.'"
