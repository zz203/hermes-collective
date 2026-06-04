# Manager Aggregation Cron Script
# Triggered by Hermes cron job at 22:00 Mon-Fri
# Loads the manager-cycle skill and runs the aggregation workflow.

set -euo pipefail

COLLECTIVE="${COLLECTIVE_PATH:-$HOME/.hermes/collective}"

echo "=== Manager Aggregation Cycle ==="
echo "Collective: $COLLECTIVE"
echo "Date: $(date +%Y-%m-%d)"
echo ""

# Pull latest
cd "$COLLECTIVE"
git pull --ff-only origin main

# Count pending inboxes
INBOX_COUNT=$(find agents/*/inbox/ -name "*.md" 2>/dev/null | wc -l)
STAGING_COUNT=$(find skills/staging/ -name "SKILL.md" 2>/dev/null | wc -l)

echo "Pending inboxes: $INBOX_COUNT"
echo "Staging skills: $STAGING_COUNT"
echo ""

if [ "$INBOX_COUNT" -eq 0 ] && [ "$STAGING_COUNT" -eq 0 ]; then
    echo "Nothing to process. Exiting."
    exit 0
fi

echo "Hermes will now load the manager-cycle workflow."
echo "Run: hermes chat -s collective/manager-cycle -q 'Manager cycle. Collective: $COLLECTIVE.'"
