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

Install `hermes-collective` on every machine that will run a manager or employee
agent:

```bash
cd hermes-collective
pip install -e .
```

Verify:

```bash
hermes-collective --version   # → 0.1.0
```

The recommended production layout is:

```text
collective-repo.git    shared bare repository for push/pull
collective-repo        manager working clone
~/.hermes/collective-* per-employee working clones
```

Do not run Hermes workflows directly inside the bare repository.

### Manager Server Setup

Run these steps on the server that hosts the shared Git repository and runs the
manager agent.

1. Create the shared bare repository:

```bash
sudo mkdir -p /srv/hermes
sudo chown -R "$USER":"$USER" /srv/hermes
git init --bare --initial-branch=main /srv/hermes/collective.git
```

2. Seed it with the Hermes Collective repository structure:

```bash
hermes-collective init --name my-team --repo /tmp/collective-seed

cd /tmp/collective-seed
git remote add origin /srv/hermes/collective.git
git push -u origin main
```

3. Create and select the manager Hermes profile:

```bash
hermes profile create overseer --clone
hermes profile use overseer
```

4. Register the manager agent with its working clone:

```bash
hermes-collective join \
  --name overseer \
  --role manager \
  --repo /srv/hermes/collective.git \
  --path ~/.hermes/collective-overseer
```

Here `--repo` is the shared bare repository, and `--path` is the manager's local
working clone. The manager workflow should always run against `--path`.

5. Verify the manager paths:

```bash
git -C /srv/hermes/collective.git rev-parse --is-bare-repository
git -C ~/.hermes/collective-overseer rev-parse --is-bare-repository
git -C ~/.hermes/collective-overseer remote -v
cat ~/.hermes/collective-overseer/agents/overseer/identity.yaml
```

Expected results:

```text
/srv/hermes/collective.git        is bare: true
~/.hermes/collective-overseer     is bare: false
origin                            points to /srv/hermes/collective.git
identity.yaml                     contains role: manager
```

### Employee Workstation Setup

Run these steps on each employee machine. Employees do not run
`hermes-collective init`; they only join the existing shared repository.

1. Configure SSH key login to the manager server. This avoids password prompts
during `git pull`, `git push`, and scheduled cron jobs.

On the employee machine:

```bash
# Create a key if this machine does not already have one
ssh-keygen -t ed25519 -C "hermes-collective-alice"

# Copy this public key
cat ~/.ssh/id_ed25519.pub
```

On the manager server, append that public key to the SSH account that owns or
can write to the shared repository:

```bash
mkdir -p ~/.ssh
chmod 700 ~/.ssh

# Paste the employee public key as one line at the end of this file
nano ~/.ssh/authorized_keys

chmod 600 ~/.ssh/authorized_keys
```

If the server uses a host alias or non-default SSH port, configure
`~/.ssh/config` on the employee machine:

```sshconfig
Host collective-server
  HostName collective-server.example.com
  Port 2222
  User gituser
```

2. Test passwordless SSH and Git access:

```bash
ssh collective-server
git ls-remote ssh://collective-server/srv/hermes/collective.git
```

3. Create and select the employee Hermes profile:

```bash
hermes profile create alice --clone
hermes profile use alice
```

4. Register the employee agent:

```bash
hermes-collective join \
  --name alice \
  --role employee \
  --repo ssh://collective-server/srv/hermes/collective.git \
  --path ~/.hermes/collective-alice
```

Here `--repo` is the shared bare repository over SSH, and `--path` is this
employee's local working clone.

For a dedicated Git user, the employee URL usually looks like:

```bash
ssh://git@MANAGER_HOST/srv/hermes/collective.git
```

5. Verify the employee clone:

```bash
git -C ~/.hermes/collective-alice remote -v
cat ~/.hermes/collective-alice/agents/alice/identity.yaml
```

Expected results:

```text
origin         points to ssh://collective-server/srv/hermes/collective.git
identity.yaml  contains role: employee
```

### Daily Workflows

Employee, inside the employee Hermes profile:

```text
/skill collective/employee-daily
```

Manager, inside the manager Hermes profile:

```text
/skill collective/manager-cycle
```

The manager skill spawns subagents that use LLM reasoning for semantic dedup and
quality assessment.

Manager CLI fallback without Hermes subagents:

```bash
hermes-collective run \
  --role manager \
  --name overseer \
  --repo ~/.hermes/collective-overseer \
  --legacy
```

### Cron Jobs

`hermes-collective setup` creates the Hermes profile, sets it as the default
Hermes profile, configures cron approvals with
`hermes -p <profile> config set approvals.cron_mode auto_approve`, installs and
starts that profile's gateway service, then installs the scheduled jobs directly
into that profile with `hermes -p <profile> cron create`. The job workdir is set
to the local collective clone, so scheduled runs load the collective repository
context automatically.

Hermes cron jobs depend on Hermes Gateway. Scheduled jobs will not run unless
Hermes Gateway is installed and running normally for the profile that owns the
jobs. Before relying on cron, verify:

```bash
hermes -p alice gateway status
hermes -p alice cron list
```

Employee cron examples:

```bash
# Employee daily reflection (6 PM Mon-Fri)
hermes -p alice cron create "0 18 * * 1-5" \
  --name collective-employee-alice \
  --workdir ~/.hermes/collective-alice \
  --skill employee-daily \
  "Run employee-daily. Collective: ~/.hermes/collective-alice. Agent: alice."

# Employee daily sync (9 AM)
hermes -p alice cron create "0 9 * * *" \
  --name collective-sync-alice \
  --workdir ~/.hermes/collective-alice \
  "cd ~/.hermes/collective-alice && git pull origin main && hermes-collective sync --repo ~/.hermes/collective-alice"
```

Manager cron examples:

```bash
# Manager cycle (10 PM Mon-Fri)
hermes -p overseer cron create "0 22 * * 1-5" \
  --name collective-manager-overseer \
  --workdir ~/.hermes/collective-overseer \
  --skill manager-cycle \
  "Run manager-cycle. Collective: ~/.hermes/collective-overseer. Agent: overseer."

# Weekly pruning (Sunday 9 AM)
hermes -p overseer cron create "0 9 * * 0" \
  --name collective-pruning-overseer \
  --workdir ~/.hermes/collective-overseer \
  --skill collective/quality-pruning \
  "Run quality pruning. Repo: ~/.hermes/collective-overseer."
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
