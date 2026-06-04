"""
Bootstrap logic — initialize a collective repo and join agents to it.

init_collective: Creates the git repo with template directory structure.
join_employee:  Clones repo, creates agent identity, installs skills, attempts cron setup.
join_manager:   Same but for the manager role.

CRON JOB CREATION:
  The bootstrap now attempts to auto-create cron jobs via `hermes cron create`
  when running inside a Hermes session (detected via HERMES_HOME env var).
  If that fails, it falls back to printing manual setup instructions.

PUSH ERROR HANDLING:
  Push operations distinguish between:
  - "no remote" (expected for local testing repos) → logged as info, not warning
  - "connection failed" (network/auth issues) → logged as error with retry hint
  - "permission denied" → logged as error immediately
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


from . import git_ops

logger = logging.getLogger(__name__)

# ── Template constants ─────────────────────────────────────────────

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "repo-structure"

AGENT_IDENTITY_TEMPLATE = """\
# {agent_name} — Identity
name: {agent_name}
role: {role}
joined: {joined}
last_sync: null
capabilities: []
tags: []
"""

GLOBAL_CONFIG_TEMPLATE = """\
# Agent Collective — Global Configuration
name: {name}
created: {created}
version: 1

# Git branch conventions
branches:
  main: main          # stable, manager-curated content
  staging: staging    # employee submissions awaiting review

# Quality thresholds
quality:
  min_score: 0.3
  stale_days: 30      # mark as stale after N days without use
  archive_days: 60    # archive if stale for N more days

# Sync schedule (for documentation; actual scheduling is via cron)
schedule:
  employee_report: "0 18 * * 1-5"   # 6 PM Mon-Fri
  manager_cycle:   "0 22 * * 1-5"   # 10 PM Mon-Fri
  quality_pruning: "0 9 * * 0"      # 9 AM Sunday
"""

README_TEMPLATE = """\
# {name} — Agent Collective

Shared knowledge repository for the {name} agent collective.

## Structure

```
agents/         — Per-agent identity and daily contribution inboxes
skills/         — Reusable procedural skills (active / staging / archive)
knowledge/      — Factual knowledge base (active / staging / archive)
failures/       — Failure experience archive (active / staging / archive)
quality/        — Quality metrics and pruning decisions
```

## Workflow

1. **Employees** do their daily work, then write summaries into their `agents/<name>/inbox/`
2. **Manager** aggregates inboxes, resolves conflicts, promotes quality content
3. **All agents** pull the latest on next sync

## Agent Roles

| Agent | Role | Host |
|-------|------|------|
"""

COLLECTIVE_SKILL_MD_TEMPLATE = """\
---
name: collective-workflow
description: "{name} collective — daily employee→manager→sync workflow. Use when doing daily report or manager aggregation for this collective."
version: 1.0.0
author: Hermes Collective
license: MIT
metadata:
  hermes:
    tags: [collective, multi-agent, knowledge-sharing, {name}]
---

# {name} Collective Workflow

## Overview

This skill maps to the {name} agent collective workflow.

## When to Use

- You are an employee agent in the {name} collective and it's end-of-day
- You are the manager agent and need to aggregate reports
- You need to sync the latest knowledge and skills

## Repository

The collective repo is at: `{repo_url}`

Local clone at: `~/.hermes/collective/`

## Employee Daily Routine

1. Review today's work using `session_search`
2. Write a daily summary to `agents/<your_name>/inbox/YYYY-MM-DD.md`
3. For reusable strategies, create candidate skills under `skills/staging/`
4. Commit and push

## Manager Cycle

1. Pull latest
2. Process each agent's inbox
3. Resolve duplicates and conflicts
4. Promote quality skills from staging to active
5. Aggregate knowledge and failures
6. Clean inboxes
7. Commit and push

## Quality Pruning

Weekly review of:
- Low-usage skills → archive
- Stale knowledge → archive
- Outdated failure patterns → archive
"""


# ── Repository initialization ─────────────────────────────────────


def init_collective(
    name: str,
    repo_path: str | Path,
    *,
    bare: bool = False,
) -> Path:
    """
    Initialize a collective git repository.

    Args:
        name: Collective name (e.g. "my-team")
        repo_path: Where to create the repository
        bare: If True, create a bare repo (for server-side)

    Returns:
        Path to the created repository
    """
    repo_path = Path(repo_path).resolve()
    now = datetime.now(timezone.utc).isoformat()

    if bare:
        # Bare repo: no working tree, just .git contents
        repo_path.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "-C", str(repo_path), "init", "--bare"], check=True)
        logger.info("Initialized bare collective repo at %s", repo_path)
        return repo_path

    if repo_path.exists() and any(repo_path.iterdir()):
        raise FileExistsError(f"Directory not empty: {repo_path}")

    repo_path.mkdir(parents=True, exist_ok=True)

    # Create directory structure
    dirs = [
        "agents",
        "skills/active",
        "skills/staging",
        "skills/archive",
        "knowledge/active",
        "knowledge/staging",
        "knowledge/archive",
        "failures/active",
        "failures/staging",
        "failures/archive",
        "quality",
        ".collective/scripts",
    ]
    for d in dirs:
        (repo_path / d).mkdir(parents=True, exist_ok=True)

    # Write template files
    _write(repo_path / "config.yaml",
           GLOBAL_CONFIG_TEMPLATE.format(name=name, created=now))
    _write(repo_path / "README.md",
           README_TEMPLATE.format(name=name))
    _write(repo_path / "quality" / "metrics.yaml",
           f"# Quality metrics — {name}\n# Updated by manager agent\nagents: {{}}\nskills: {{}}\nknowledge: {{}}\nfailures: {{}}\n")
    _write(repo_path / "quality" / "pruning-log.yaml",
           f"# Pruning decisions log — {name}\n# Format: {{date: {{item: reason}}}}\n")
    _write(repo_path / ".gitkeep", "")

    # Create agent READMEs
    for sub in ["agents", "skills/active", "knowledge/active", "failures/active"]:
        _write(repo_path / sub / ".gitkeep", "")

    # Init git and make initial commit
    git_ops.init_repo(repo_path)
    git_ops.add_and_commit(repo_path, f"🎉 Initialize {name} collective")

    logger.info("Initialized collective '%s' at %s", name, repo_path)
    return repo_path


# ── Agent registration ────────────────────────────────────────────


def join_employee(
    name: str,
    repo_url: str,
    local_path: str | Path | None = None,
) -> dict:
    """
    Register an employee agent.

    Args:
        name: Agent display name (e.g. "alice")
        repo_url: Git URL of the collective repo (ssh or https)
        local_path: Where to clone locally (default: ~/.hermes/collective-<name>/)

    Returns:
        dict with paths and next-step instructions
    """
    local_path = Path(local_path) if local_path else Path.home() / ".hermes" / f"collective-{name}"
    skills_dir = Path.home() / ".hermes" / "skills"

    # Clone repo (skip if already exists)
    if not (local_path / ".git").exists():
        logger.info("Cloning collective repo...")
        git_ops.clone(repo_url, local_path)
    else:
        logger.info("Collective repo already exists at %s, pulling...", local_path)
        git_ops.pull(local_path)

    # Create agent directory and identity
    agent_dir = local_path / "agents" / name
    agent_dir.mkdir(parents=True, exist_ok=True)
    inbox_dir = agent_dir / "inbox"
    inbox_dir.mkdir(exist_ok=True)

    identity_file = agent_dir / "identity.yaml"
    if not identity_file.exists():
        _write(identity_file,
               AGENT_IDENTITY_TEMPLATE.format(
                   agent_name=name,
                   role="employee",
                   joined=datetime.now(timezone.utc).isoformat(),
               ))

    # Install collective skills into Hermes skills directory
    plugin_skills = Path(__file__).parent / "skills"
    installed_skills = _install_skills(plugin_skills, skills_dir, role="employee")

    # Create sync script
    sync_script = _create_sync_script(local_path, name, role="employee", repo_url=repo_url)

    # Commit identity
    git_ops.add_and_commit(
        local_path,
        f"👤 Register employee agent: {name}",
        files=[f"agents/{name}/", str(Path(sync_script).relative_to(local_path))],
    )

    # Attempt push with proper error handling
    _safe_push(local_path, name, "employee")

    # Attempt auto cron creation
    cron_results = _auto_create_crons(name, role="employee", local_path=local_path)

    # Build next-steps
    next_steps = _build_cron_instructions(name, role="employee", local_path=local_path,
                                          cron_results=cron_results)

    return {
        "local_path": str(local_path),
        "agent_dir": str(agent_dir),
        "installed_skills": installed_skills,
        "sync_script": sync_script,
        "next_steps": next_steps,
        "cron_results": cron_results,
    }


def join_manager(
    name: str,
    repo_path: str | Path,
    local_path: str | Path | None = None,
) -> dict:
    """
    Register the manager agent.

    The manager typically runs on the same server as the repo,
    so repo_path is a local path (not a URL).
    """
    repo_path = Path(repo_path).resolve()
    local_path = Path(local_path) if local_path else repo_path
    skills_dir = Path.home() / ".hermes" / "skills"

    if not git_ops.is_repo(local_path):
        # If local_path exists but is not a git repo, remove it first
        if local_path.exists():
            if any(local_path.iterdir()):
                logger.warning("Removing non-repo directory: %s", local_path)
            shutil.rmtree(local_path)
        logger.info("Cloning from local repo...")
        git_ops.clone(str(repo_path), local_path)

    # Create agent directory and identity
    agent_dir = local_path / "agents" / name
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "decisions").mkdir(exist_ok=True)

    identity_file = agent_dir / "identity.yaml"
    if not identity_file.exists():
        _write(identity_file,
               AGENT_IDENTITY_TEMPLATE.format(
                   agent_name=name,
                   role="manager",
                   joined=datetime.now(timezone.utc).isoformat(),
               ))

    # Install manager skills
    plugin_skills = Path(__file__).parent / "skills"
    installed_skills = _install_skills(plugin_skills, skills_dir, role="manager")

    # Create sync script
    sync_script = _create_sync_script(local_path, name, role="manager", repo_url=str(repo_path))

    git_ops.add_and_commit(
        local_path,
        f"👤 Register manager agent: {name}",
        files=[f"agents/{name}/", str(Path(sync_script).relative_to(local_path))],
    )

    # Attempt push with proper error handling
    _safe_push(local_path, name, "manager")

    # Attempt auto cron creation
    cron_results = _auto_create_crons(name, role="manager", local_path=local_path)

    next_steps = _build_cron_instructions(name, role="manager", local_path=local_path,
                                          cron_results=cron_results)

    return {
        "local_path": str(local_path),
        "agent_dir": str(agent_dir),
        "installed_skills": installed_skills,
        "sync_script": sync_script,
        "next_steps": next_steps,
        "cron_results": cron_results,
    }


# ── Push error handling ────────────────────────────────────────────


def _safe_push(repo_path: Path, agent_name: str, role: str) -> None:
    """
    Push to origin with proper error classification.

    Distinguishes between:
    - No remote configured (testing / local dev → info)
    - Network/auth failures (→ error with retry hint)
    - Permission denied (→ error, needs fix)
    """
    # Check if remote is configured
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "remote", "get-url", "origin"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            logger.info(
                "Push skipped — no remote configured for %s. "
                "Add a remote: git remote add origin <url>",
                repo_path,
            )
            return
        remote_url = result.stdout.strip()
    except Exception:
        logger.info("Push skipped — could not determine remote URL.")
        return

    # Determine if this is a local or remote URL
    is_local = (
        remote_url.startswith("/")
        or remote_url.startswith("file://")
        or not remote_url.startswith(("http", "git@", "ssh://"))
    )

    try:
        git_ops.push(repo_path)
        logger.info("Pushed identity for %s (%s) to remote.", agent_name, role)

    except Exception as e:
        error_msg = str(e).lower()

        if is_local:
            # Local repo — push may not be meaningful
            logger.info(
                "Push skipped for local repo at %s — this is normal for testing. "
                "The repo will work for local collective operations.",
                repo_path,
            )
        elif "permission denied" in error_msg or "403" in error_msg:
            logger.error(
                "❌ Push failed: Permission denied to %s. "
                "Check your SSH key or HTTPS credentials.",
                remote_url,
            )
            raise
        elif "could not resolve host" in error_msg or "connection" in error_msg:
            logger.error(
                "❌ Push failed: Cannot reach %s. "
                "Check your network connection and try again later.",
                remote_url,
            )
            raise
        else:
            logger.warning(
                "⚠ Push failed for %s: %s. You can push manually later.",
                agent_name, e,
            )


# ── Helpers ────────────────────────────────────────────────────────


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _install_skills(plugin_skills_dir: Path, skills_dir: Path, role: str) -> list[str]:
    """Copy skill files from plugin to Hermes skills directory. Returns list of skill names."""
    installed = []

    # Skills to install based on role
    skill_names = (
        ["employee-daily", "quality-pruning"]
        if role == "employee"
        else ["manager-cycle", "quality-pruning"]
    )

    for skill_name in skill_names:
        src = plugin_skills_dir / skill_name / "SKILL.md"
        if not src.exists():
            logger.warning("Skill not found in plugin: %s", skill_name)
            continue

        dst = skills_dir / "collective" / skill_name / "SKILL.md"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        installed.append(skill_name)

    return installed


def _create_sync_script(local_path: Path, name: str, role: str, repo_url: str) -> str:
    """Create a shell script for daily sync. Returns the script path."""
    script_dir = local_path / ".collective" / "scripts"
    script_dir.mkdir(parents=True, exist_ok=True)

    script_path = script_dir / f"{role}-daily.sh"
    script_path.write_text(
        "#!/bin/bash\n"
        "set -euo pipefail\n"
        f'COLLECTIVE="{local_path}"\n'
        f'AGENT="{name}"\n'
        f'ROLE="{role}"\n'
        "\n"
        'echo "=== Collective Sync: $ROLE ($AGENT) ===\"\n'
        "cd \"$COLLECTIVE\"\n"
        "git pull --ff-only origin main\n"
        "\n"
        "# Trigger Hermes to run the daily skill\n"
        f'hermes chat -q "Load skill collective/{role}-daily and '
        f'follow its instructions. '
        f'Collective path: {local_path}. Agent name: {name}." '
        f'--skills collective/{role}-daily\n'
        "\n"
        'echo "=== Sync complete ===\"\n'
    )
    script_path.chmod(0o755)
    return str(script_path)


def _auto_create_crons(name: str, role: str, local_path: Path) -> dict:
    """
    Attempt to auto-create cron jobs via hermes CLI.

    Returns {"success": [...], "failed": [...]} listing which crons were created.
    Only attempts if running inside a Hermes session (detected by HERMES_HOME env var).
    """
    results = {"success": [], "failed": []}

    # Check if we're in a Hermes session
    hermes_home = os.environ.get("HERMES_HOME")
    if not hermes_home:
        logger.info(
            "Not in Hermes session (HERMES_HOME not set). "
            "Cron jobs must be created manually."
        )
        return results

    # Check if hermes cron command is available
    try:
        subprocess.run(["hermes", "cron", "--help"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        logger.info(
            "`hermes cron` command not available. Cron jobs must be created manually."
        )
        return results

    cron_defs = []
    if role == "employee":
        cron_defs.extend([
            {
                "schedule": "0 18 * * *",
                "name": f"collective-employee-{name}",
                "skills": "employee-daily",
                "prompt": (
                    f"Run the end-of-work collective report as {name}. "
                    f"Collective repo: {local_path}. "
                    f"Use {name}_reflection_checkpoint in memory. "
                    f"Follow the employee-daily skill (v2 incremental reflection)."
                ),
            },
            {
                "schedule": "0 9 * * *",
                "name": f"collective-sync-{name}",
                "skills": "",
                "prompt": (
                    f"Pull latest from collective at {local_path} "
                    f"and sync skills: cd {local_path} && git pull origin main "
                    f"&& hermes-collective sync --repo {local_path}"
                ),
            },
            {
                "schedule": "0 9 * * 0",
                "name": f"collective-pruning-{name}",
                "skills": "collective/quality-pruning",
                "prompt": (
                    f"Run collective quality pruning. Repo: {local_path}. "
                    f"Follow the quality-pruning skill."
                ),
            },
        ])
    else:  # manager
        cron_defs.extend([
            {
                "schedule": "0 22 * * *",
                "name": f"collective-manager-{name}",
                "skills": "manager-cycle",
                "prompt": (
                    f"Run the manager aggregation cycle as {name}. "
                    f"Collective repo: {local_path}. "
                    f"Follow the manager-cycle skill."
                ),
            },
            {
                "schedule": "0 9 * * 0",
                "name": f"collective-pruning-{name}",
                "skills": "collective/quality-pruning",
                "prompt": (
                    f"Run collective quality pruning. Repo: {local_path}. "
                    f"Follow the quality-pruning skill."
                ),
            },
        ])

    for cron_def in cron_defs:
        try:
            cmd = [
                "hermes", "cron", "create",
                cron_def["schedule"],
                "--name", cron_def["name"],
            ]
            if cron_def["skills"]:
                cmd.extend(["--skill", cron_def["skills"]])
            cmd.append(cron_def["prompt"])

            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                results["success"].append(cron_def["name"])
                logger.info("✅ Cron created: %s", cron_def["name"])
            else:
                results["failed"].append((cron_def["name"], result.stderr.strip()))
                logger.warning(
                    "⚠ Failed to create cron '%s': %s",
                    cron_def["name"], result.stderr.strip(),
                )
        except Exception as e:
            results["failed"].append((cron_def["name"], str(e)))
            logger.warning("⚠ Could not create cron '%s': %s", cron_def["name"], e)

    return results


def _build_cron_instructions(
    name: str, role: str, local_path: Path,
    cron_results: dict | None = None,
) -> str:
    """Build instructions for setting up cron jobs via Hermes."""
    cron_results = cron_results or {"success": [], "failed": []}

    lines = [
        f"\n📋 == Next Steps for '{name}' ({role}) ==\n",
    ]

    # Show auto-created crons
    if cron_results["success"]:
        lines.append("✅ Auto-created cron jobs:")
        for job_name in cron_results["success"]:
            lines.append(f"   • {job_name}")
        lines.append("")

    if cron_results["failed"]:
        lines.append("⚠ Failed to create these cron jobs (create manually):")
        for job_name, err in cron_results["failed"]:
            lines.append(f"   • {job_name}: {err}")
        lines.append("")

    # Show manual instructions for any not auto-created
    if not cron_results["success"] or cron_results["failed"]:
        lines.append("Manual cron setup (run inside a Hermes session):")
        lines.append("")

    if role == "employee":
        if not cron_results["success"]:
            lines += [
                "1. Set up daily reflection cron inside a Hermes session:",
                "",
                '   hermes cron create "0 18 * * *" \\\\',
                f'     --name collective-employee-{name} \\\\',
                '     --skill employee-daily \\\\',
                f'     "Run the end-of-work collective report as {name}. '
                f'Collective repo: {local_path}. '
                f'Use {name}_reflection_checkpoint in memory. '
                f'Follow the employee-daily skill (v2 incremental reflection)."',
                "",
                "2. Set up daily sync (pull collective updates):",
                "",
                '   hermes cron create "0 9 * * *" \\\\',
                f'     --name collective-sync-{name} \\\\',
                f'     "Pull latest from collective at {local_path} '
                f'and sync skills: cd {local_path} && git pull origin main '
                f'&& hermes-collective sync --repo {local_path}"',
                "",
            ]
    else:
        if not cron_results["success"]:
            lines += [
                "1. Set up daily management cron inside a Hermes session:",
                "",
                '   hermes cron create "0 22 * * *" \\\\',
                f'     --name collective-manager-{name} \\\\',
                '     --skill manager-cycle \\\\',
                f'     "Run the manager aggregation cycle as {name}. '
                f'Collective repo: {local_path}. '
                f'Follow the manager-cycle skill."',
                "",
            ]

    lines += [
        "2. Or run manually to test:",
        f"   hermes chat -s collective/{'employee-daily' if role == 'employee' else 'manager-cycle'} "
        f"-q 'Run workflow. Collective: {local_path}. Agent: {name}.'",
        "",
        "3. Set up weekly pruning (any agent can run this):",
        '   hermes cron create "0 9 * * 0" --name collective-pruning \\\\',
        f'     --skill collective/quality-pruning \\\\',
        f'     "Run collective quality pruning. Repo: {local_path}."',
        "",
    ]

    return "\n".join(lines)
