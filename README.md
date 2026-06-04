# Hermes Collective

**Multi-Agent Collective Learning System for Hermes Agent**

A git-based shared knowledge repository where multiple Hermes employee agents contribute daily learnings, and a manager agent aggregates, curates, and maintains quality.

> **v2 Update:** Manager aggregation now uses `delegate_task` subagents for LLM-powered semantic dedup, quality scoring, and conflict resolution. The Python library (`aggregator.py`) provides tool functions that subagents call via `execute_code`. A legacy mechanical pipeline is available as fallback via `--legacy`.

## Concept

```
┌──────────┐   ┌──────────┐   ┌──────────┐
│ Employee │   │ Employee │   │ Employee │    Different computers
│  Alice   │   │   Bob    │   │  Carol   │    Different tasks
└────┬─────┘   └────┬─────┘   └────┬─────┘
     │              │              │
     │  18:00       │  18:00       │  18:00
     │  Daily       │  Daily       │  Daily
     │  Report      │  Report      │  Report
     ▼              ▼              ▼
┌──────────────────────────────────────────┐
│         Git Repository (Server)          │
│  agents/*/inbox/  skills/staging/        │
└──────────────────┬───────────────────────┘
                   │
                   │  22:00
                   │  Manager Cycle
                   ▼
┌──────────────────────────────────────────┐
│     Manager Agent (Hermes session)       │
│  ┌─────────────────────────────────┐     │
│  │ delegate_task → Subagent 1     │     │
│  │   LLM: extract knowledge,      │     │
│  │   semantic dedup, failures     │     │
│  ├─────────────────────────────────┤     │
│  │ delegate_task → Subagent 2     │     │
│  │   LLM: score skills, detect    │     │
│  │   duplicates, promote/reject   │     │
│  ├─────────────────────────────────┤     │
│  │ Tool functions (aggregator.py) │     │
│  │   promote_skill, write_knowledge, │  │
│  │   write_failure, commit, push  │     │
│  └─────────────────────────────────┘     │
│  skills/active/  knowledge/active/       │
│  failures/active/                       │
└──────────────────┬───────────────────────┘
                   │
                   │  Next day 09:00
                   │  Sync
                   ▼
     ┌─────────────┼─────────────┐
     ▼             ▼             ▼
┌──────────┐ ┌──────────┐ ┌──────────┐
│ Employee │ │ Employee │ │ Employee │    Pull updated skills
│  Alice   │ │   Bob    │ │  Carol   │    & knowledge
└──────────┘ └──────────┘ └──────────┘
```

## Architecture

### Manager Aggregation (v2 — Subagent-Driven)

The manager cycle is now **orchestrated by a Hermes skill** that spawns subagents for intelligent decision-making:

| Task | Legacy (mechanical) | v2 (subagent + LLM) |
|------|--------------------|---------------------|
| Dedup detection | SHA256 hash — different whitespace = "unique" | LLM reads both, semantically compares |
| Quality scoring | Counts regex matches (headings, code blocks) | LLM evaluates structure, actionability, completeness |
| Knowledge extraction | Regex heading parsing | LLM understands context, extracts salient facts |
| Conflict resolution | "Keep longer side" | LLM evaluates both sides on merit |

The Python library (`hermes_collective.aggregator`) provides **tool functions** that subagents call via `execute_code`:
- **Scanner**: `scan_inboxes`, `scan_staging_skills`, `scan_active_skills`
- **Reader**: `read_inbox`, `read_skill`, `get_existing_knowledge`, `get_existing_failures`
- **Writer**: `promote_skill`, `keep_skill_in_staging`, `reject_skill`, `merge_skills`, `write_knowledge`, `write_failure`, `clean_inbox`, `clean_all_inboxes`
- **Git**: `commit_changes`, `push_changes`, `pull_latest`

A legacy mechanical pipeline is available via `--legacy` for environments without Hermes.

## Quick Start

### 1. Install

```bash
cd hermes-collective
pip install -e .
```

Verify:
```bash
hermes-collective --version   # → 0.1.0
```

### 2. Initialize the Collective

```bash
# Create the repository
hermes-collective init --name my-team --repo ~/collective-repo

# Push to remote (optional but recommended)
cd ~/collective-repo
git remote add origin git@github.com:myteam/collective.git
git push -u origin main
```

### 3. Register Agents

```bash
# Manager (on the server)
hermes-collective join --name overseer --repo ~/collective-repo --role manager

# Employees (on each workstation)
hermes-collective join --name alice --repo git@github.com:myteam/collective.git --role employee
hermes-collective join --name bob   --repo git@github.com:myteam/collective.git --role employee
```

### 4. Daily Workflows

**Employee (inside a Hermes session):**
```
/skill collective/employee-daily
```

**Manager — recommended (inside a Hermes session):**
```
/skill collective/manager-cycle
```

This spawns subagents that use LLM reasoning for semantic dedup and quality assessment.

**Manager — CLI fallback (no Hermes required):**
```bash
hermes-collective run --role manager --repo ~/collective-repo --legacy
```

### 5. Cron Jobs

```bash
# Employee daily reflection (6 PM Mon-Fri)
hermes cron create "0 18 * * 1-5" \
  --name collective-employee-alice \
  --skills employee-daily \
  --prompt "Run employee-daily. Collective: ~/.hermes/collective-alice. Agent: alice."

# Employee daily sync (9 AM)
hermes cron create "0 9 * * *" \
  --name collective-sync-alice \
  --prompt "cd ~/.hermes/collective-alice && git pull origin main && hermes-collective sync --repo ~/.hermes/collective-alice"

# Manager cycle (10 PM Mon-Fri)
hermes cron create "0 22 * * 1-5" \
  --name collective-manager-overseer \
  --skills manager-cycle \
  --prompt "Run manager-cycle. Collective: ~/collective-repo. Agent: overseer."

# Weekly pruning (Sunday 9 AM)
hermes cron create "0 9 * * 0" \
  --name collective-pruning \
  --prompt "Run quality pruning. Repo: ~/collective-repo." \
  --skills collective/quality-pruning
```

## Commands

| Command | Description |
|---------|-------------|
| `hermes-collective init` | Initialize a new collective repo |
| `hermes-collective join` | Register an agent (employee or manager) |
| `hermes-collective run --role employee` | Create inbox template and sync skills |
| `hermes-collective run --role manager --legacy` | Run mechanical aggregation pipeline |
| `hermes-collective run --role manager` | Inside Hermes: guides you to use the skill |
| `hermes-collective prune-cmd --dry-run` | Preview what would be pruned |
| `hermes-collective prune-cmd` | Prune low-quality stale items |
| `hermes-collective status` | Show collective status and quality report |
| `hermes-collective sync` | Pull latest and sync skills to ~/.hermes/skills/ |
| `hermes-collective setup` | Interactive setup wizard |

## Skills

| Skill | Role | Purpose |
|-------|------|---------|
| `collective/employee-daily` | Employee | End-of-day reflection: checkpoint-based, extract learnings, share to collective |
| `collective/manager-cycle` | Manager | v2: orchestrates subagents for LLM-powered aggregation, dedup, and skill review |
| `collective/quality-pruning` | Both | Weekly quality scoring and stale item archiving |

## Repository Structure

```
collective-repo/
├── agents/<name>/          Per-agent identity & daily inbox
│   ├── identity.yaml
│   ├── inbox/              Raw daily reports (consumed by manager)
│   └── decisions/          Manager decision log
├── skills/
│   ├── active/             Curated, verified skills (all agents sync)
│   ├── staging/            Employee candidate submissions
│   └── archive/            Archived skills (never deleted)
├── knowledge/
│   ├── active/             Curated factual knowledge
│   ├── staging/            Candidate knowledge
│   └── archive/
├── failures/
│   ├── active/             Curated failure archive (by year/month)
│   ├── staging/
│   └── archive/
├── quality/                Metrics, scores, pruning log
├── config.yaml             Global collective config
└── .collective/scripts/    Automation shell scripts
```

## Quality System

Items are scored on: usage frequency, freshness, completeness, specificity, redundancy, and staleness.

- **Score ≥ 0.7**: Excellent
- **Score 0.4–0.7**: Good
- **Score 0.2–0.4**: At risk
- **Score < 0.2**: Archive candidate

Default pruning: score < 0.3 AND stale > 60 days → archive.

## Development

```bash
pip install -e ".[dev]"     # Install with test dependencies
pytest                      # 87 tests
ruff check .                # Lint
```

## License

MIT
