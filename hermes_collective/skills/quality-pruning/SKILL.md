---
name: quality-pruning
description: "Use when running periodic quality maintenance on the collective knowledge base. Score all active items, identify low-quality or stale content, archive or remove, and update quality metrics."
version: 1.0.0
author: Hermes Collective
license: MIT
metadata:
  hermes:
    tags: [collective, quality, pruning, maintenance]
---

# Quality Pruning

## Overview

Over time, the collective knowledge base accumulates content. Some becomes outdated, some was never very useful, and some has been superseded by better versions. This skill runs weekly to identify and archive low-quality items, keeping the knowledge base lean and trustworthy.

## When to Use

- Weekly cron fires (Sunday 9 AM by default)
- The collective feels cluttered and you want to clean up
- After a major system migration that obsoleted many old skills

## Scoring Dimensions

Each item in `skills/active/`, `knowledge/active/`, and `failures/active/` is scored on:

| Dimension | Weight | Description |
|-----------|--------|-------------|
| Freshness | 20% | How recently was this updated? |
| Usage | 25% | How often is this loaded or referenced? |
| Completeness | 15% | Does it have frontmatter, sections, code examples? |
| Specificity | 15% | Is it specific enough to be useful? |
| Redundancy | 15% | Low overlap with other items (less redundant = better) |
| Age | 10% | How long has this been in the active set? |

## Workflow

### Step 1: Generate Quality Report

```bash
cd ~/.hermes/collective
hermes-collective prune --dry-run
```

Or run programmatically:
```python
from hermes_collective.quality import score_all, get_quality_report
print(get_quality_report(Path("~/.hermes/collective").expanduser()))
```

### Step 2: Review Low-Scoring Items

Items below the threshold (default 0.3) AND stale (default 60+ days without use):

For each candidate for archiving, decide:

| Decision | Condition | Action |
|----------|-----------|--------|
| **Archive** | Truly obsolete or superseded | Move to `*/archive/` |
| **Keep** | Still potentially useful | Update `last_used` timestamp, add note why kept |
| **Merge** | Duplicate of another item | Merge content, remove the weaker one |
| **Improve** | Good concept, poor execution | Add a TODO note in meta.yaml, keep in active |

### Step 3: Execute Pruning

```bash
hermes-collective prune --threshold 0.3 --stale-days 60
```

Without `--dry-run`, this:
1. Moves archived items to their respective `archive/` directories
2. Logs each decision in `quality/pruning-log.yaml`
3. Updates `quality/metrics.yaml`

### Step 4: Commit

```bash
cd ~/.hermes/collective
git add -A
git commit -m "🧹 Weekly quality pruning — archived N items"
git push origin main
```

## What to Archive

**Definitely archive:**
- Skills for tools that no longer exist or have been replaced
- Knowledge about deprecated API versions
- Failure reports for bugs that were permanently fixed 6+ months ago
- Skills with 0 usage in 60+ days and low completeness score
- Duplicate skills (merge first, archive the extra)

**Be cautious about archiving:**
- Infrastructure knowledge — even if rarely used, it's critical when needed
- Security-related failure reports — these patterns can recur
- Skills with low usage but high completeness — might just be for rare but important tasks

## Pruning Decision Log Format

Each pruning run writes to `quality/pruning-log.yaml`:

```yaml
2026-05-15T09:00:00:
  action: prune
  count: 5
  items:
    - name: deploy-legacy-app
      type: skill
      score: 0.15
      stale_days: 90
      reason: "Tool deprecated, replaced by deploy-modern-app"
    - name: ubuntu-18-config
      type: knowledge
      score: 0.10
      stale_days: 120
      reason: "OS version EOL"
```

## Restoring Archived Items

Archived items are never deleted — they move to `*/archive/`. To restore:

```bash
# Restore a skill
mv skills/archive/<skill-name> skills/active/<skill-name>

# Restore knowledge
mv knowledge/archive/<file>.md knowledge/active/<file>.md

# Don't forget to commit
git add -A && git commit -m "♻️ Restore <item> from archive" && git push
```

## Common Pitfalls

1. **Archiving too aggressively** — a skill unused for 60 days might still be valuable. Check why it's unused before archiving.
2. **Not reading the content** — don't prune based on score alone. Open and read low-scoring items before deciding.
3. **Archiving the only skill for a domain** — if it's the only PostgreSQL skill and it's just slightly stale, improve it instead.
4. **Forgetting to push** — pruned items won't be removed from other agents' views until they pull.

## Verification Checklist

- [ ] Quality report generated and reviewed
- [ ] Each archived item has a logged reason
- [ ] No critical infrastructure knowledge was accidentally archived
- [ ] Archive directories contain the moved items
- [ ] pruning-log.yaml updated
- [ ] Commit pushed successfully
