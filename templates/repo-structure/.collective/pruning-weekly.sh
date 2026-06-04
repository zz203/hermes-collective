# Weekly Quality Pruning Script
# Triggered by Hermes cron job on Sunday 9 AM
# Loads the quality-pruning skill and archives low-quality items.

set -euo pipefail

COLLECTIVE="${COLLECTIVE_PATH:-$HOME/.hermes/collective}"

echo "=== Weekly Quality Pruning ==="
echo "Collective: $COLLECTIVE"
echo "Date: $(date +%Y-%m-%d)"
echo ""

cd "$COLLECTIVE"
git pull --ff-only origin main

echo "Hermes will now load the quality-pruning workflow."
echo "Run: hermes chat -s collective/quality-pruning -q 'Quality pruning. Collective: $COLLECTIVE.'"
