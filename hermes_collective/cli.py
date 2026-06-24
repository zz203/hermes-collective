"""
CLI for hermes-collective — the multi-agent collective learning system.

Commands:
    hermes-collective setup     Interactive setup (choose role, auto-configure everything)
    hermes-collective init      Initialize a new collective repo
    hermes-collective join      Register an agent (employee or manager)
    hermes-collective run       Run daily workflow (employee or manager)
    hermes-collective prune     Run quality pruning
    hermes-collective status    Show collective status
    hermes-collective sync      Pull latest and sync local skills

Usage:
    hermes-collective setup                          # Interactive wizard
    hermes-collective init --name my-team --repo /srv/collective
    hermes-collective join --name alice --repo git@server:collective.git --role employee
    hermes-collective run --role employee
    hermes-collective status
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
from pathlib import Path

import click
import yaml

from . import __version__
from .aggregator import (
    scan_inboxes, scan_staging_skills, read_inbox, read_skill, write_knowledge, write_failure,
    promote_skill, keep_skill_in_staging, reject_skill,
    clean_all_inboxes,
    commit_changes, push_changes,
)
from .bootstrap import (
    init_collective,
    join_employee,
    join_manager,
    _install_skills,
    _create_crons,
    _cron_definitions,
)
from .quality import get_quality_report, prune

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)


def _resolve_path(path: str) -> Path:
    """Resolve ~ and relative paths."""
    return Path(path).expanduser().resolve()


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run a command, return result. Prints stdout/stderr live."""
    return subprocess.run(cmd, check=False, text=True, **kwargs)


def _merge_cron_results(*results: dict | None) -> dict:
    """Merge cron result dictionaries returned by bootstrap helpers."""
    merged = {"success": [], "failed": [], "skipped": []}
    for result in results:
        if not result:
            continue
        for key in merged:
            merged[key].extend(result.get(key, []))
    return merged


def _print_cron_results(cron_results: dict) -> None:
    """Print a concise cron setup summary."""
    if cron_results["success"]:
        click.echo("   Created:")
        for job_name in cron_results["success"]:
            click.echo(f"     ✅ {job_name}")

    if cron_results["skipped"]:
        click.echo("   Already present / skipped:")
        for job_name in cron_results["skipped"]:
            click.echo(f"     • {job_name}")

    if cron_results["failed"]:
        click.echo("   Failed:")
        for job_name, error in cron_results["failed"]:
            click.echo(f"     ⚠ {job_name}: {error}")


def _print_manual_cron_commands(
    name: str,
    role: str,
    local_path: Path,
    reflect_hour: int = 18,
    pull_hour: int | None = 9,
    manage_hour: int = 22,
) -> None:
    """Print profile-aware manual cron create commands."""
    cron_defs = _cron_definitions(
        name=name,
        role=role,
        local_path=local_path,
        reflect_hour=reflect_hour,
        pull_hour=pull_hour,
        manage_hour=manage_hour,
        include_pruning=True,
    )

    click.echo()
    click.echo("   Manual fallback commands:")
    for cron_def in cron_defs:
        click.echo()
        click.echo(f"   hermes -p {name} cron create \"{cron_def['schedule']}\" \\")
        click.echo(f"     --name {cron_def['name']} \\")
        click.echo(f"     --workdir {local_path} \\")
        if cron_def["skills"]:
            click.echo(f"     --skill {cron_def['skills']} \\")
        click.echo(f"     \"{cron_def['prompt']}\"")


def _ensure_profile_gateway_service(profile: str) -> dict:
    """Install and start the Hermes gateway service for a profile."""
    result = {"success": [], "failed": []}
    commands = [
        ("install", ["hermes", "-p", profile, "gateway", "install"]),
        ("start", ["hermes", "-p", profile, "gateway", "start"]),
    ]

    for action, cmd in commands:
        completed = _run(cmd, capture_output=True)
        if completed.returncode == 0:
            result["success"].append(action)
        else:
            error = (completed.stderr or completed.stdout or f"exit {completed.returncode}").strip()
            result["failed"].append((action, error))

    return result


def _print_gateway_results(profile: str, gateway_results: dict) -> None:
    """Print gateway setup results and fallback commands."""
    if not gateway_results["failed"]:
        click.echo("   Gateway service installed and started.")
        return

    if gateway_results["success"]:
        click.echo(f"   Gateway steps completed: {', '.join(gateway_results['success'])}")

    click.echo("   Gateway service setup needs attention:")
    for action, error in gateway_results["failed"]:
        click.echo(f"     ⚠ {action}: {error}")
    click.echo("   Manual fallback commands:")
    click.echo(f"     hermes -p {profile} gateway install")
    click.echo(f"     hermes -p {profile} gateway start")


def _use_profile(profile: str) -> dict:
    """Make the Hermes profile the sticky default profile."""
    completed = _run(["hermes", "profile", "use", profile], capture_output=True)
    if completed.returncode == 0:
        return {"success": True, "error": ""}

    error = (completed.stderr or completed.stdout or f"exit {completed.returncode}").strip()
    return {"success": False, "error": error}


def _print_profile_use_result(profile: str, profile_result: dict) -> None:
    """Print profile switching result and fallback command."""
    if profile_result["success"]:
        click.echo(f"   Default Hermes profile set to '{profile}'.")
        return

    click.echo(f"   ⚠ Could not switch default profile: {profile_result['error']}")
    click.echo("   Manual fallback command:")
    click.echo(f"     hermes profile use {profile}")


def _configure_cron_approvals(profile: str) -> dict:
    """Allow profile cron jobs to auto-approve required actions."""
    cmd = [
        "hermes",
        "-p", profile,
        "config", "set",
        "approvals.cron_mode",
        "auto_approve",
    ]
    completed = _run(cmd, capture_output=True)
    if completed.returncode == 0:
        return {"success": True, "error": ""}

    error = (completed.stderr or completed.stdout or f"exit {completed.returncode}").strip()
    return {"success": False, "error": error}


def _print_cron_approval_result(profile: str, approval_result: dict) -> None:
    """Print cron approval config result and fallback command."""
    if approval_result["success"]:
        click.echo("   Cron approval mode set to auto_approve.")
        return

    click.echo(f"   ⚠ Could not set cron approval mode: {approval_result['error']}")
    click.echo("   Manual fallback command:")
    click.echo(f"     hermes -p {profile} config set approvals.cron_mode auto_approve")


# ── setup (interactive wizard) ─────────────────────────────────────


@click.group(invoke_without_command=True)
@click.version_option(__version__, prog_name="hermes-collective")
@click.pass_context
def main(ctx):
    """Hermes Collective — Multi-Agent Collective Learning System."""
    if ctx.invoked_subcommand is None:
        # Default: run setup wizard
        setup_wizard()


@main.command()
def setup():
    """Interactive setup wizard — choose role, configure everything."""
    setup_wizard()


def setup_wizard():
    """Interactive setup flow."""
    click.echo()
    click.echo("╔══════════════════════════════════════════╗")
    click.echo("║   Hermes Collective — Agent Setup       ║")
    click.echo("╚══════════════════════════════════════════╝")
    click.echo()
    click.echo("Welcome! This wizard will configure your agent")
    click.echo("for the multi-agent collective learning system.")
    click.echo()

    # ── Step 1: Choose role ──
    role = click.prompt(
        "Choose your role",
        type=click.Choice(["employee", "manager"]),
        default="employee",
        show_choices=True,
    ).strip()

    click.echo()
    if role == "employee":
        click.echo("📝 Employee Role:")
        click.echo("   - You will reflect on your work daily")
        click.echo("   - Extract errors, skills, and knowledge")
        click.echo("   - Share learnings with the collective via git")
    else:
        click.echo("📋 Manager Role:")
        click.echo("   - You will aggregate reports from all employees")
        click.echo("   - Curate skills, resolve conflicts")
        click.echo("   - Maintain the collective knowledge base")
    click.echo()

    # ── Step 2: Agent name ──
    name = click.prompt(
        "Agent name (unique identifier, e.g. 'alice')",
        type=str,
        default="alice" if role == "employee" else "overseer",
    ).strip().lower().replace(" ", "-")

    # ── Step 3: Repo URL ──
    repo_default = (
        str(Path.home() / ".hermes" / f"collective-{name}")
        if role == "employee"
        else str(Path.home() / "collective-demo.git")
    )
    repo_url = click.prompt(
        "Collective repository (git URL or local path)",
        type=str,
        default=repo_default,
    ).strip()

    # ── Step 4: Role-specific config ──
    if role == "employee":
        reflect_time = click.prompt(
            "Daily reflection time (cron: hour)",
            type=int,
            default=18,
        )
        pull_time = click.prompt(
            "Daily sync/pull time (cron: hour, 0 to skip)",
            type=int,
            default=9,
        )
    else:
        manage_time = click.prompt(
            "Daily management time (cron: hour)",
            type=int,
            default=22,
        )

    click.echo()
    click.echo("─" * 44)
    click.echo("  Summary:")
    click.echo(f"    Role:        {role}")
    click.echo(f"    Agent name:  {name}")
    click.echo(f"    Repository:  {repo_url}")
    if role == "employee":
        click.echo(f"    Reflection:  daily at {reflect_time}:00")
        if pull_time > 0:
            click.echo(f"    Sync/pull:   daily at {pull_time}:00")
    else:
        click.echo(f"    Management:  daily at {manage_time}:00")
    click.echo("─" * 44)
    click.echo()

    if not click.confirm("Proceed with setup?", default=True):
        click.echo("Aborted.")
        return

    # ── Step 5: Create Hermes Profile ──
    click.echo()
    click.echo(f"👤 Creating Hermes Profile '{name}'...")
    result = _run(["hermes", "profile", "create", name, "--clone"],
                  capture_output=True)
    if result.returncode != 0:
        click.echo(f"⚠️  Profile creation note: {result.stderr.strip()}")
        click.echo("   Continuing anyway...")
    else:
        click.echo(f"   ✅ Profile '{name}' created at ~/.hermes/profiles/{name}/")
        click.echo(f"   Wrapper: {name} chat  (runs hermes -p {name})")

    click.echo()
    click.echo(f"🔁 Switching default Hermes profile to '{name}'...")
    profile_use_result = _use_profile(name)
    _print_profile_use_result(name, profile_use_result)

    # ── Step 6: Configure cron approvals ──
    click.echo()
    click.echo("🔐 Configuring cron approvals...")
    cron_approval_result = _configure_cron_approvals(name)
    _print_cron_approval_result(name, cron_approval_result)

    # ── Step 7: Clone and register ──
    click.echo()
    click.echo("📦 Cloning collective repository...")

    local_path = Path.home() / ".hermes" / f"collective-{name}"

    try:
        if role == "employee":
            result = join_employee(name=name, repo_url=repo_url, local_path=local_path)
        else:
            result = join_manager(name=name, repo_path=repo_url, local_path=local_path)

        click.echo(f"   ✅ Agent '{name}' ({role}) registered!")
        click.echo(f"   Local clone: {result['local_path']}")
        click.echo(f"   Skills installed: {', '.join(result['installed_skills'])}")

        # Also install skills into the profile
        profile_skills = Path.home() / ".hermes" / "profiles" / name / "skills"
        plugin_skills = Path(__file__).parent / "skills"
        _install_skills(plugin_skills, profile_skills, role=role)
        click.echo("   Profile skills synced")

    except Exception as e:
        click.echo(f"❌ Failed to register: {e}", err=True)
        sys.exit(1)

    # ── Step 8: Setup profile gateway service ──
    click.echo()
    click.echo("🔌 Setting up Hermes Gateway service...")
    click.echo(f"   Installing service for Hermes profile '{name}'...")
    gateway_results = _ensure_profile_gateway_service(name)
    _print_gateway_results(name, gateway_results)

    # ── Step 9: Setup cron jobs ──
    click.echo()
    click.echo("⏰ Setting up cron jobs...")
    click.echo(f"   Creating jobs in Hermes profile '{name}'...")

    precreated_crons = result.get("cron_results", {})

    if role == "employee":
        setup_crons = _create_crons(
            name=name,
            role=role,
            local_path=local_path,
            profile=name,
            reflect_hour=reflect_time,
            pull_hour=pull_time,
        )
        cron_results = _merge_cron_results(precreated_crons, setup_crons)
        _print_cron_results(cron_results)

    else:  # manager
        setup_crons = _create_crons(
            name=name,
            role=role,
            local_path=local_path,
            profile=name,
            manage_hour=manage_time,
        )
        cron_results = _merge_cron_results(precreated_crons, setup_crons)
        _print_cron_results(cron_results)

    if cron_results["failed"]:
        _print_manual_cron_commands(
            name=name,
            role=role,
            local_path=local_path,
            reflect_hour=reflect_time if role == "employee" else 18,
            pull_hour=pull_time if role == "employee" else 9,
            manage_hour=manage_time if role == "manager" else 22,
        )

    click.echo()
    click.echo("   Test with:")
    click.echo(f"     hermes -p {name} cron list")
    click.echo(f"     hermes -p {name} cron run <job-id>")

    # ── Step 10: Done ──
    click.echo()
    click.echo("══════════════════════════════════════════")
    click.echo(f"  ✅ {name} ({role}) is ready!")
    click.echo("══════════════════════════════════════════")
    click.echo()
    click.echo(f"  Profile:    {name} chat")
    click.echo(f"  Repo:       {local_path}")
    click.echo(f"  Identity:   {local_path}/agents/{name}/identity.yaml")
    click.echo()
    if cron_results["failed"]:
        click.echo("  Some cron jobs still need manual setup; see the commands above.")
    elif not cron_approval_result["success"]:
        click.echo("  Gateway and cron jobs were configured, but cron approval setup failed.")
    elif not profile_use_result["success"]:
        click.echo("  Gateway and cron jobs were configured, but default profile switching failed.")
    elif gateway_results["failed"]:
        click.echo("  Cron jobs were configured, but the profile gateway service needs attention.")
    else:
        click.echo("  Gateway service and cron jobs were configured in the Hermes profile.")
    click.echo()


# ── init ───────────────────────────────────────────────────────────


@main.command()
@click.option("--name", "-n", required=True, help="Collective name (e.g. 'my-team')")
@click.option("--repo", "-r", required=True, help="Path for the collective git repo")
@click.option("--bare", is_flag=True, help="Create a bare repo (for server-side)")
def init(name: str, repo: str, bare: bool):
    """Initialize a new collective repository."""
    repo_path = _resolve_path(repo)

    try:
        result = init_collective(name=name, repo_path=repo_path, bare=bare)
        click.echo(f"✅ Collective '{name}' initialized at {result}")
        click.echo()
        click.echo("Next steps:")
        click.echo(f"  1. Push to a remote: cd {result} && git remote add origin <url> && git push -u origin main")
        click.echo("  2. Register agents: hermes-collective setup")
    except FileExistsError as e:
        click.echo(f"❌ {e}", err=True)
        sys.exit(1)


# ── join ───────────────────────────────────────────────────────────


@main.command()
@click.option("--name", "-n", required=True, help="Agent name (e.g. 'alice')")
@click.option("--repo", "-r", required=True, help="Git URL or local path to the collective repo")
@click.option("--role", "-R", type=click.Choice(["employee", "manager"]), default="employee",
              help="Agent role")
@click.option("--path", "-p", default=None, help="Local clone path (default: ~/.hermes/collective-<name>/)")
def join(name: str, repo: str, role: str, path: str | None):
    """Register an agent in the collective."""
    local_path = _resolve_path(path) if path else None

    try:
        if role == "employee":
            result = join_employee(name=name, repo_url=repo, local_path=local_path)
        else:
            result = join_manager(name=name, repo_path=repo, local_path=local_path)

        click.echo(f"✅ Agent '{name}' ({role}) registered!")
        click.echo(f"   Local clone: {result['local_path']}")
        click.echo(f"   Skills installed: {', '.join(result['installed_skills'])}")
        click.echo(result["next_steps"])
    except Exception as e:
        click.echo(f"❌ {e}", err=True)
        sys.exit(1)


# ── run ────────────────────────────────────────────────────────────


@main.command()
@click.option("--role", "-R", type=click.Choice(["employee", "manager"]), required=True,
              help="Which role workflow to run")
@click.option("--name", "-n", default=None, help="Agent name (auto-detected if omitted)")
@click.option("--repo", "-r", default=None, help="Collective repo path (default: ~/.hermes/collective/)")
@click.option("--dry-run", is_flag=True, help="Preview without making changes")
@click.option("--legacy", is_flag=True, help="Use legacy mechanical pipeline (no LLM subagents)")
def run(role: str, name: str | None, repo: str | None, dry_run: bool, legacy: bool):
    """Run a daily workflow cycle.

    For manager role: the recommended approach is to load the manager-cycle
    skill inside a Hermes session, which uses delegate_task subagents for
    LLM-powered semantic scoring and dedup. This CLI mode uses the legacy
    mechanical pipeline as a fallback.

    For employee role: creates an inbox template and syncs skills.
    """
    repo_path = _resolve_path(repo) if repo else Path.home() / ".hermes" / "collective"

    if not repo_path.exists():
        click.echo(
            f"❌ Collective not found at {repo_path}. Run 'hermes-collective setup' first.",
            err=True,
        )
        sys.exit(1)

    # Auto-detect agent name from repo
    if not name:
        agents_dir = repo_path / "agents"
        if agents_dir.exists():
            for agent_dir in agents_dir.iterdir():
                identity_file = agent_dir / "identity.yaml"
                if identity_file.exists():
                    identity = yaml.safe_load(identity_file.read_text()) or {}
                    if identity.get("role") == role or role == "employee":
                        name = identity.get("name", agent_dir.name)
                        break

    click.echo(f"🚀 Running {role} workflow for '{name or 'unknown'}'...")
    click.echo(f"   Repo: {repo_path}")
    if dry_run:
        click.echo("   [DRY RUN MODE]")
    if legacy:
        click.echo("   [LEGACY MODE — mechanical pipeline, no LLM subagents]")

    if role == "manager":
        # Check if running inside Hermes (where subagent orchestration is possible)
        hermes_home = os.environ.get("HERMES_HOME")

        if hermes_home and not legacy:
            click.echo()
            click.echo("✨ Preferred: run inside a Hermes session with the manager-cycle skill")
            click.echo("   The skill uses delegate_task subagents for LLM-powered:")
            click.echo("   • Semantic deduplication of skills and knowledge")
            click.echo("   • Intelligent quality scoring (not just regex counting)")
            click.echo("   • Context-aware conflict resolution")
            click.echo()
            click.echo("   To use:  /skill collective/manager-cycle")
            click.echo("   Or:      hermes chat -s collective/manager-cycle")
            click.echo()

        # Run the legacy mechanical pipeline (fallback)
        click.echo("📥 Step 1: Inventory — scanning inboxes and staging...")

        inboxes = scan_inboxes(repo_path)
        staging = scan_staging_skills(repo_path)

        click.echo(f"   Inboxes to process: {len(inboxes)}")
        for ib in inboxes:
            click.echo(f"     • {ib['agent']} — {ib['date']}")
        click.echo(f"   Staging skills: {len(staging)}")
        for s in staging:
            click.echo(f"     • {s['name']}")

        if not inboxes and not staging:
            click.echo()
            click.echo("✨ Nothing to process. All caught up!")
            return

        click.echo()
        if hermes_home and not legacy:
            click.echo("💡 To process these with LLM intelligence:")
            click.echo("   /skill collective/manager-cycle")
            click.echo()
            click.echo("   Or run the legacy mechanical pipeline:")
            click.echo(f"   hermes-collective run --role manager --repo {repo_path} --legacy")
            return

        # Legacy mechanical pipeline
        import datetime

        knowledge_added = 0
        failures_added = 0

        # Process each inbox mechanically
        click.echo("📝 Step 2: Processing inboxes (mechanical)...")
        for ib in inboxes:
            data = read_inbox(ib["path"])
            sections = data["sections"]

            knowledge = sections.get("knowledge", "")
            if knowledge:
                topic = "general"
                heading = re.match(r"^###?\s+(.+)$", knowledge.strip(), re.MULTILINE)
                if heading:
                    topic = re.sub(r"[^a-z0-9-]", "", heading.group(1).lower())[:30]
                if dry_run:
                    knowledge_added += 1
                else:
                    result = write_knowledge(
                        repo_path, topic, knowledge,
                        source_agent=ib["agent"], source_date=ib["date"],
                        check_duplicate=True,
                    )
                    if result.get("action") != "skipped":
                        knowledge_added += 1

            failures = sections.get("failures", "")
            if failures:
                failures_added += 1
                if not dry_run:
                    write_failure(
                        repo_path, failures,
                        source_agent=ib["agent"], date=ib["date"],
                        check_duplicate=True,
                    )

        # Review each staging skill mechanically
        click.echo("🔍 Step 3: Reviewing staging skills (mechanical)...")
        skills_promoted = 0
        skills_kept = 0
        skills_rejected = 0

        for stg in staging:
            skill = read_skill(stg["path"])
            content = skill["content"]

            # Simple heuristic scoring (mechanical fallback)
            score = 0.0
            if content.startswith("---") and content.count("---") >= 2:
                score += 0.15
            headings = len(re.findall(r"^##\s+", content, re.MULTILINE))
            score += min(headings * 0.05, 0.20)
            if "```" in content:
                score += 0.10
            if "pitfall" in content.lower():
                score += 0.10
            if "verification" in content.lower() or "checklist" in content.lower():
                score += 0.10
            if len(content) > 300:
                score += 0.10
            if len(content) > 800:
                score += 0.10
            score = min(score + 0.10, 1.0)  # baseline

            if dry_run:
                if score >= 0.5:
                    click.echo(f"   [DRY RUN] {stg['name']}: score={score:.2f} → would promote")
                    skills_promoted += 1
                elif score >= 0.2:
                    click.echo(f"   [DRY RUN] {stg['name']}: score={score:.2f} → would keep")
                    skills_kept += 1
                else:
                    click.echo(f"   [DRY RUN] {stg['name']}: score={score:.2f} → would reject")
                    skills_rejected += 1
            elif score >= 0.5:
                promote_skill(repo_path, stg["name"], score)
                skills_promoted += 1
                click.echo(f"   ✅ Promoted: {stg['name']} (score={score:.2f})")
            elif score >= 0.2:
                keep_skill_in_staging(
                    repo_path, stg["name"],
                    f"Score {score:.2f} — needs improvement (mechanical review)",
                )
                skills_kept += 1
                click.echo(f"   ⏸ Kept: {stg['name']} (score={score:.2f})")
            else:
                reject_skill(repo_path, stg["name"], f"Score {score:.2f} below threshold")
                skills_rejected += 1
                click.echo(f"   ❌ Rejected: {stg['name']} (score={score:.2f})")

        click.echo()
        click.echo("📊 Summary:")
        click.echo(f"   Knowledge items added: {knowledge_added}")
        click.echo(f"   Failure logs added:    {failures_added}")
        click.echo(f"   Skills promoted:       {skills_promoted}")
        click.echo(f"   Skills kept:           {skills_kept}")
        click.echo(f"   Skills rejected:       {skills_rejected}")

        if not dry_run:
            click.echo()
            click.echo("🧹 Step 4: Cleaning up...")
            clean_all_inboxes(repo_path)

            today = datetime.datetime.now().strftime("%Y-%m-%d")
            commit_changes(repo_path, f"📋 Manager cycle: {today} [legacy mechanical]")
            push_result = push_changes(repo_path)
            click.echo(f"   Push: {push_result.get('action', 'done')}")

        click.echo()
        click.echo("✅ Manager cycle complete.")
        if hermes_home and not legacy:
            click.echo()
            click.echo("💡 For better results, use the manager-cycle skill in Hermes:")
            click.echo("   /skill collective/manager-cycle")

    elif role == "employee":
        click.echo()
        click.echo("📥 Step 1: Pulling latest from collective...")
        from . import git_ops
        git_ops.pull(repo_path)

        click.echo()
        click.echo("📝 Step 2: Running employee daily workflow...")
        click.echo()

        import datetime

        # Create a starter inbox file for today
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        active_skills_dir = repo_path / "skills" / "active"
        active_skills = []
        if active_skills_dir.exists():
            active_skills = [
                d.name for d in active_skills_dir.iterdir()
                if d.is_dir() and (d / "SKILL.md").exists()
            ]

        if active_skills:
            from .quality import bulk_update_usage
            bulk_update_usage(repo_path, "skill", active_skills)
            click.echo(f"   📊 Tracked usage for {len(active_skills)} active skills")

        inbox_dir = repo_path / "agents" / name / "inbox"
        inbox_dir.mkdir(parents=True, exist_ok=True)
        inbox_file = inbox_dir / f"{today}.md"

        if not inbox_file.exists():
            inbox_file.write_text(
                f"# Daily Reflection — {name} — {today}\n\n"
                "## What I Worked On\n"
                "<Describe your sessions and tasks today>\n\n"
                "## Learnings Shared\n\n"
                "### New Skills Created\n"
                "<list skills created and their paths under skills/staging/>\n\n"
                "### Skills Patched\n"
                "<list skills updated and what was fixed>\n\n"
                "### Knowledge Discovered\n"
                "<new facts, API quirks, patterns worth sharing>\n\n"
                "### Failures Encountered\n"
                "- **Problem:** <what went wrong>\n"
                "- **Root cause:** <why>\n"
                "- **Fix:** <how resolved>\n"
            )
            click.echo(f"   📄 Created inbox template: agents/{name}/inbox/{today}.md")
        else:
            click.echo(f"   📄 Inbox already exists: agents/{name}/inbox/{today}.md")

        # Show what's waiting in staging
        staging_dir = repo_path / "skills" / "staging"
        staging_count = 0
        if staging_dir.exists():
            staging_count = len([d for d in staging_dir.iterdir() if d.is_dir()])
        click.echo(f"   📦 Staging skills awaiting manager review: {staging_count}")

        click.echo()
        click.echo("📋 Next — complete the daily report:")
        click.echo(f"   1. Fill in your inbox: {inbox_file}")
        click.echo("   2. For shareable skills, copy to: skills/staging/candidate-<name>/")
        click.echo("   3. From a Hermes session, run the employee-daily skill:")
        click.echo("      /skill collective/employee-daily")
        click.echo("   4. Or run: hermes chat -s collective/employee-daily \\")
        click.echo(f"      -q 'Run daily report. Collective: {repo_path}. Agent: {name}.'")

        click.echo()
        click.echo("✅ Employee sync complete. Ready for daily report.")


# ── prune ──────────────────────────────────────────────────────────


@main.command()
@click.option("--repo", "-r", default=None, help="Collective repo path")
@click.option("--threshold", "-t", default=0.3, type=float, help="Score threshold for pruning (0.0-1.0)")
@click.option("--stale-days", "-s", default=60, type=int, help="Days stale before archiving")
@click.option("--dry-run", is_flag=True, help="Preview what would be pruned")
def prune_cmd(repo: str | None, threshold: float, stale_days: int, dry_run: bool):
    """Prune low-quality, stale items from the collective."""
    repo_path = _resolve_path(repo) if repo else Path.home() / ".hermes" / "collective"

    if not repo_path.exists():
        click.echo(f"❌ Collective not found at {repo_path}", err=True)
        sys.exit(1)

    click.echo(get_quality_report(repo_path))
    click.echo()

    click.echo(f"🔍 Scanning for items below score {threshold}, stale > {stale_days} days...")
    result = prune(repo_path, threshold=threshold, stale_days=stale_days, dry_run=dry_run)

    total = sum(result.values())
    if total == 0:
        click.echo("✨ No items need pruning.")
    elif dry_run:
        click.echo(f"[DRY RUN] Would archive {total} items:")
        for category, count in result.items():
            if count:
                click.echo(f"  {category}: {count}")
        click.echo()
        click.echo("Run without --dry-run to execute.")
    else:
        click.echo(f"🗑️  Archived {total} items:")
        for category, count in result.items():
            if count:
                click.echo(f"  {category}: {count}")
        click.echo("✅ Pruning complete.")


# ── status ─────────────────────────────────────────────────────────


@main.command()
@click.option("--repo", "-r", default=None, help="Collective repo path")
def status(repo: str | None):
    """Show collective status — agents, skills, quality."""
    repo_path = _resolve_path(repo) if repo else Path.home() / ".hermes" / "collective"

    if not repo_path.exists():
        click.echo(f"❌ Collective not found at {repo_path}", err=True)
        sys.exit(1)

    click.echo("📊 Collective Status")
    click.echo(f"   Repo: {repo_path}")
    click.echo()

    from . import git_ops
    if git_ops.is_repo(repo_path):
        gs = git_ops.status(repo_path)
        if gs.strip():
            click.echo("   ⚠️  Uncommitted changes:")
            for line in gs.strip().split("\n"):
                click.echo(f"      {line}")
        else:
            click.echo("   ✅ Git: clean")
    click.echo()

    agents_dir = repo_path / "agents"
    if agents_dir.exists():
        click.echo("   👥 Agents:")
        for agent_dir in sorted(agents_dir.iterdir()):
            if not agent_dir.is_dir():
                continue
            identity_file = agent_dir / "identity.yaml"
            if identity_file.exists():
                identity = yaml.safe_load(identity_file.read_text()) or {}
                role = identity.get("role", "unknown")
                inbox_count = len(list((agent_dir / "inbox").glob("*.md"))) if (agent_dir / "inbox").exists() else 0
                click.echo(f"      {agent_dir.name} ({role}) — {inbox_count} pending inbox items")
    click.echo()

    for section in ["active", "staging", "archive"]:
        skills_dir = repo_path / "skills" / section
        if skills_dir.exists():
            count = len([d for d in skills_dir.iterdir() if d.is_dir()])
            click.echo(f"   📚 Skills ({section}): {count}")
    click.echo()

    for section in ["active", "staging"]:
        kdir = repo_path / "knowledge" / section
        if kdir.exists():
            count = len(list(kdir.glob("*.md")))
            click.echo(f"   📖 Knowledge ({section}): {count}")
    click.echo()

    click.echo(get_quality_report(repo_path))


# ── sync ───────────────────────────────────────────────────────────


@main.command()
@click.option("--repo", "-r", default=None, help="Collective repo path")
def sync(repo: str | None):
    """Pull latest from collective and sync skills to ~/.hermes/skills/."""
    repo_path = _resolve_path(repo) if repo else Path.home() / ".hermes" / "collective"

    if not repo_path.exists():
        click.echo(f"❌ Collective not found at {repo_path}", err=True)
        sys.exit(1)

    import shutil

    from . import git_ops
    from .quality import bulk_update_usage

    click.echo("📥 Pulling latest...")
    git_ops.pull(repo_path)

    skills_src = repo_path / "skills" / "active"
    skills_dst = Path.home() / ".hermes" / "skills" / "collective"
    skills_dst.mkdir(parents=True, exist_ok=True)

    synced = 0
    skill_names = []
    if skills_src.exists():
        for skill_dir in skills_src.iterdir():
            if not skill_dir.is_dir():
                continue
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                continue

            dst = skills_dst / skill_dir.name / "SKILL.md"
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(skill_file, dst)
            skill_names.append(skill_dir.name)
            synced += 1

    # Track usage for synced skills
    if skill_names:
        bulk_update_usage(repo_path, "skill", skill_names)

    click.echo(f"✅ Synced {synced} skills to {skills_dst}")
    if skill_names:
        click.echo(f"   Updated usage metrics for: {', '.join(skill_names)}")
    click.echo("   Run /reload-skills in Hermes or start a new session to load them.")


if __name__ == "__main__":
    main()
