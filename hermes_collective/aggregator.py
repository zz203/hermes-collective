"""
Collective tool functions — mechanical operations for the collective repository.

These are pure tool functions designed to be called by subagents via execute_code,
or directly by the manager-cycle skill orchestrator. They do NOT contain any
intelligence (no scoring, no dedup logic, no decision-making). All intelligence
lives in the manager-cycle skill and its delegated subagents.

Tool categories:
- Scanner: list inboxes, staging skills, active skills
- Reader: read inbox content, skill content, existing knowledge
- Writer: promote/reject skills, write knowledge/failures, clean inboxes
- Git: commit and push
- Quality: update usage metrics, get quality reports
"""

from __future__ import annotations

import logging
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import git_ops
from .quality import update_usage

logger = logging.getLogger(__name__)

# ── Scanner functions ──────────────────────────────────────────────


def scan_inboxes(repo_path: str | Path) -> list[dict]:
    """
    List all non-empty inbox files across all agents.

    Returns list of {agent, date, path, content_hash}.
    Called by subagents to discover what needs processing.
    """
    repo_path = Path(repo_path)
    items = []

    agents_dir = repo_path / "agents"
    if not agents_dir.exists():
        return items

    for agent_dir in sorted(agents_dir.iterdir()):
        if not agent_dir.is_dir():
            continue
        inbox_dir = agent_dir / "inbox"
        if not inbox_dir.exists():
            continue

        for inbox_file in sorted(inbox_dir.glob("*.md")):
            content = inbox_file.read_text(encoding="utf-8").strip()
            if content:
                import hashlib
                items.append({
                    "agent": agent_dir.name,
                    "date": inbox_file.stem,
                    "path": str(inbox_file),
                    "content_hash": hashlib.sha256(content.encode()).hexdigest()[:16],
                })

    return items


def scan_staging_skills(repo_path: str | Path) -> list[dict]:
    """
    List all candidate skills in staging.

    Returns list of {name, path, has_meta}.
    """
    repo_path = Path(repo_path)
    staging_dir = repo_path / "skills" / "staging"
    skills = []

    if not staging_dir.exists():
        return skills

    for skill_dir in sorted(staging_dir.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            continue
        skills.append({
            "name": skill_dir.name,
            "path": str(skill_file),
            "has_meta": (skill_dir / "meta.yaml").exists(),
        })

    return skills


def scan_active_skills(repo_path: str | Path) -> list[dict]:
    """
    List all active skills.

    Returns list of {name, path}.
    """
    repo_path = Path(repo_path)
    active_dir = repo_path / "skills" / "active"
    skills = []

    if not active_dir.exists():
        return skills

    for skill_dir in sorted(active_dir.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            continue
        skills.append({
            "name": skill_dir.name,
            "path": str(skill_file),
        })

    return skills


# ── Reader functions ───────────────────────────────────────────────


def read_inbox(path: str) -> dict:
    """
    Read an inbox file and return its content with parsed sections.

    Returns {agent, date, raw_content, sections: {section_name: content}}.
    """
    file_path = Path(path)
    raw = file_path.read_text(encoding="utf-8").strip()

    # Parse agent and date from path
    parts = file_path.parts
    agent = parts[-3] if len(parts) >= 3 else "unknown"
    date = file_path.stem

    # Parse sections
    sections = {}
    current_section = "_preamble"
    current_lines = []

    for line in raw.split("\n"):
        m = re.match(r"^##\s+(.+)$", line)
        if m:
            if current_lines:
                sections[current_section] = "\n".join(current_lines).strip()
            current_section = m.group(1).lower().replace(" ", "_")
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        sections[current_section] = "\n".join(current_lines).strip()

    return {
        "agent": agent,
        "date": date,
        "raw_content": raw,
        "sections": sections,
    }


def read_skill(path: str) -> dict:
    """
    Read a skill's SKILL.md and meta.yaml.

    Returns {name, content, frontmatter, meta}.
    """
    skill_file = Path(path)
    content = skill_file.read_text(encoding="utf-8")

    # Parse YAML frontmatter
    frontmatter = {}
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            try:
                frontmatter = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError:
                pass

    # Read meta if exists
    meta = {}
    meta_file = skill_file.parent / "meta.yaml"
    if meta_file.exists():
        try:
            meta = yaml.safe_load(meta_file.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            pass

    return {
        "name": skill_file.parent.name,
        "content": content,
        "frontmatter": frontmatter,
        "meta": meta,
    }


def get_existing_knowledge(repo_path: str | Path, topic: str = "") -> dict:
    """
    Read existing knowledge from the knowledge base.

    If topic is given, returns that specific file's content.
    Otherwise returns a summary of all knowledge topics.
    """
    repo_path = Path(repo_path)
    knowledge_dir = repo_path / "knowledge" / "active"

    if not knowledge_dir.exists():
        return {"topics": [], "content": {}}

    if topic:
        target = knowledge_dir / f"{topic}.md"
        if target.exists():
            return {
                "topics": [topic],
                "content": {topic: target.read_text(encoding="utf-8")},
            }
        return {"topics": [], "content": {}}

    topics = {}
    for kfile in sorted(knowledge_dir.glob("*.md")):
        if kfile.name == ".gitkeep":
            continue
        topics[kfile.stem] = kfile.read_text(encoding="utf-8")[:5000]  # First 5KB

    return {"topics": list(topics.keys()), "content": topics}


def get_existing_failures(repo_path: str | Path) -> list[dict]:
    """
    List recent failure reports for dedup checking.

    Returns list of {path, first_line, date, agent}.
    """
    repo_path = Path(repo_path)
    failures_dir = repo_path / "failures" / "active"
    results = []

    if not failures_dir.exists():
        return results

    for ffile in sorted(failures_dir.rglob("*.md"), reverse=True)[:50]:  # Last 50
        if ffile.name == ".gitkeep":
            continue
        content = ffile.read_text(encoding="utf-8")
        first_line = content.strip().split("\n")[0].strip("# ").strip()
        results.append({
            "path": str(ffile),
            "first_line": first_line,
            "preview": content[:500],
        })

    return results


# ── Writer functions ───────────────────────────────────────────────


def promote_skill(repo_path: str | Path, skill_name: str, score: float = 0.0) -> dict:
    """
    Promote a skill from staging to active.

    If an active skill with the same name exists, merges content.
    Updates usage metrics and meta.yaml.
    """
    repo_path = Path(repo_path)
    staging_dir = repo_path / "skills" / "staging" / skill_name
    active_dir = repo_path / "skills" / "active" / skill_name

    if not staging_dir.exists():
        return {"error": f"Staging skill '{skill_name}' not found"}

    now = datetime.now(timezone.utc).isoformat()

    if active_dir.exists():
        # Merge: append new sections from staging to existing active
        _merge_skill_md(active_dir / "SKILL.md", staging_dir / "SKILL.md")
        logger.info("Merged staging skill into existing active: %s", skill_name)
        action = "merged"
    else:
        shutil.copytree(staging_dir, active_dir)
        logger.info("Promoted staging skill to active: %s", skill_name)
        action = "promoted"

    # Update meta
    _append_meta(active_dir / "meta.yaml", "promoted_at", now)
    if score:
        _append_meta(active_dir / "meta.yaml", "promoted_score", score)

    # Track usage
    update_usage(repo_path, "skill", skill_name)

    # Remove from staging
    shutil.rmtree(staging_dir)

    return {"action": action, "skill": skill_name, "score": score}


def keep_skill_in_staging(repo_path: str | Path, skill_name: str, note: str = "") -> dict:
    """
    Keep a skill in staging with a feedback note.
    """
    repo_path = Path(repo_path)
    meta_file = repo_path / "skills" / "staging" / skill_name / "meta.yaml"

    _append_meta(meta_file, "review_notes", {
        "date": datetime.now(timezone.utc).isoformat(),
        "note": note,
    })

    return {"action": "kept", "skill": skill_name, "note": note}


def reject_skill(repo_path: str | Path, skill_name: str, reason: str = "") -> dict:
    """
    Remove a low-quality skill from staging and log the decision.
    """
    repo_path = Path(repo_path)
    staging_path = repo_path / "skills" / "staging" / skill_name

    if not staging_path.exists():
        return {"error": f"Staging skill '{skill_name}' not found"}

    # Log rejection
    _log_decision(repo_path, "rejected_skill", {
        "name": skill_name,
        "rejected_at": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
    })

    shutil.rmtree(staging_path)
    logger.info("Rejected staging skill: %s (%s)", skill_name, reason)

    return {"action": "rejected", "skill": skill_name, "reason": reason}


def merge_skills(repo_path: str | Path, source: str, target: str) -> dict:
    """
    Merge source skill into target skill.

    Can be staging→active, active→active, or staging→staging.
    """
    repo_path = Path(repo_path)

    # Find source
    for section in ["staging", "active"]:
        src_path = repo_path / "skills" / section / source / "SKILL.md"
        if src_path.exists():
            break
    else:
        return {"error": f"Source skill '{source}' not found"}

    # Find target
    for section in ["staging", "active"]:
        tgt_path = repo_path / "skills" / section / target / "SKILL.md"
        if tgt_path.exists():
            break
    else:
        return {"error": f"Target skill '{target}' not found"}

    _merge_skill_md(tgt_path, src_path)

    # Record merge
    _append_meta(tgt_path.parent / "meta.yaml", "merged_from", {
        "skill": source,
        "merged_at": datetime.now(timezone.utc).isoformat(),
    })

    logger.info("Merged '%s' into '%s'", source, target)
    return {"action": "merged", "source": source, "target": target}


def delete_skill(repo_path: str | Path, skill_name: str, section: str = "staging") -> dict:
    """Delete a skill from staging or active."""
    repo_path = Path(repo_path)
    skill_path = repo_path / "skills" / section / skill_name

    if not skill_path.exists():
        return {"error": f"Skill '{skill_name}' not found in {section}"}

    shutil.rmtree(skill_path)
    return {"action": "deleted", "skill": skill_name, "section": section}


def write_knowledge(
    repo_path: str | Path,
    topic: str,
    content: str,
    source_agent: str = "",
    source_date: str = "",
    check_duplicate: bool = False,
) -> dict:
    """
    Write a knowledge entry to the knowledge base.

    If check_duplicate=True and similar content exists, returns {skipped: true}.
    """
    repo_path = Path(repo_path)
    knowledge_dir = repo_path / "knowledge" / "active"
    knowledge_dir.mkdir(parents=True, exist_ok=True)

    # Sanitize topic
    topic = re.sub(r"[^a-z0-9-]", "", topic.lower()) or "general"
    target = knowledge_dir / f"{topic}.md"

    entry_annotation = ""
    if source_agent or source_date:
        entry_annotation = f"<!-- source: {source_agent} | date: {source_date} -->\n"

    full_entry = f"\n\n{entry_annotation}{content.strip()}\n"

    if check_duplicate and target.exists():
        existing = target.read_text(encoding="utf-8")
        if _content_similarity(full_entry, existing) > 0.80:
            return {"action": "skipped", "topic": topic, "reason": "similar content exists"}

    if target.exists():
        existing = target.read_text(encoding="utf-8")
        target.write_text(existing + full_entry, encoding="utf-8")
    else:
        target.write_text(f"# {topic.replace('-', ' ').title()}\n\n{full_entry}", encoding="utf-8")

    update_usage(repo_path, "knowledge", topic)
    return {"action": "written", "topic": topic, "file": str(target)}


def write_failure(
    repo_path: str | Path,
    content: str,
    source_agent: str = "",
    date: str = "",
    check_duplicate: bool = False,
) -> dict:
    """
    Write a failure report to the failure archive.

    Organizes by year/month. If check_duplicate=True, merges with similar failures.
    """
    repo_path = Path(repo_path)
    date = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    year, month, _ = date.split("-")

    first_line = content.strip().split("\n")[0].strip("# ").strip()
    slug = re.sub(r"[^a-z0-9-]", "", first_line.lower())[:50] or "untitled"

    target_dir = repo_path / "failures" / "active" / year / month
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{date}_{source_agent}_{slug}.md"

    formatted = (
        f"# {first_line}\n\n"
        f"**Source:** {source_agent}\n"
        f"**Date:** {date}\n\n"
        f"{content.strip()}\n"
    )

    if check_duplicate:
        # Check existing failures for similarity
        for existing_file in target_dir.glob("*.md"):
            if existing_file.name == ".gitkeep":
                continue
            existing_text = existing_file.read_text(encoding="utf-8")
            if _content_similarity(content, existing_text) > 0.80:
                merged = (
                    existing_text.rstrip()
                    + f"\n\n<!-- merged from {source_agent} on {date} -->\n"
                    + content.strip() + "\n"
                )
                existing_file.write_text(merged, encoding="utf-8")
                update_usage(repo_path, "failure",
                             str(existing_file.relative_to(repo_path / "failures" / "active")))
                return {"action": "merged", "file": str(existing_file), "reason": "similar failure exists"}

    target.write_text(formatted, encoding="utf-8")
    update_usage(repo_path, "failure",
                 str(target.relative_to(repo_path / "failures" / "active")))
    return {"action": "written", "file": str(target)}


def clean_inbox(repo_path: str | Path, agent: str, date: str) -> dict:
    """Remove a processed inbox file."""
    repo_path = Path(repo_path)
    inbox_file = repo_path / "agents" / agent / "inbox" / f"{date}.md"

    if inbox_file.exists():
        inbox_file.unlink()
        return {"action": "cleaned", "agent": agent, "date": date}
    return {"action": "not_found", "agent": agent, "date": date}


def clean_all_inboxes(repo_path: str | Path) -> dict:
    """Remove all processed inbox files."""
    items = scan_inboxes(repo_path)
    cleaned = 0
    for item in items:
        Path(item["path"]).unlink()
        cleaned += 1
    return {"action": "cleaned_all", "count": cleaned}


# ── Git operations ──────────────────────────────────────────────────


def commit_changes(repo_path: str | Path, message: str) -> dict:
    """Stage all changes and commit."""
    repo_path = Path(repo_path)
    git_ops.add_and_commit(repo_path, message)
    return {"action": "committed", "message": message}


def push_changes(repo_path: str | Path) -> dict:
    """Push to origin (best-effort)."""
    repo_path = Path(repo_path)
    try:
        result = git_ops.push(repo_path)
        return {"action": "pushed", "result": result}
    except Exception as e:
        return {"action": "push_failed", "error": str(e)}


def pull_latest(repo_path: str | Path) -> dict:
    """Pull latest from origin (best-effort)."""
    repo_path = Path(repo_path)
    try:
        result = git_ops.pull(repo_path)
        return {"action": "pulled", "result": result}
    except Exception as e:
        return {"action": "pull_failed", "error": str(e)}


# ── Quality helpers ─────────────────────────────────────────────────


def get_quality_summary(repo_path: str | Path) -> dict:
    """Get a quick quality summary of the collective."""
    from .quality import score_all

    reports = score_all(Path(repo_path))
    summary = {
        "total_items": len(reports),
        "by_type": {},
        "average_score": 0.0,
    }

    for r in reports:
        summary["by_type"].setdefault(r.item_type, {
            "count": 0, "avg_score": 0.0, "scores": [],
        })
        bt = summary["by_type"][r.item_type]
        bt["count"] += 1
        bt["scores"].append(r.score)

    for bt in summary["by_type"].values():
        bt["avg_score"] = round(sum(bt["scores"]) / len(bt["scores"]), 2) if bt["scores"] else 0.0
        del bt["scores"]

    if reports:
        summary["average_score"] = round(sum(r.score for r in reports) / len(reports), 2)

    return summary


# ── Internal helpers ────────────────────────────────────────────────


def _content_similarity(a: str, b: str) -> float:
    """Compute content similarity (SequenceMatcher + Jaccard blend)."""
    if not a.strip() or not b.strip():
        return 0.0
    from difflib import SequenceMatcher
    sm = SequenceMatcher(None, a.lower(), b.lower()).ratio()
    a_words = set(a.lower().split())
    b_words = set(b.lower().split())
    if not a_words or not b_words:
        return sm
    jaccard = len(a_words & b_words) / len(a_words | b_words)
    return sm * 0.7 + jaccard * 0.3


def _merge_skill_md(existing: Path, incoming: Path) -> None:
    """Merge incoming skill content into existing, appending new sections only."""
    existing_content = existing.read_text(encoding="utf-8")
    incoming_content = incoming.read_text(encoding="utf-8")

    inc_sections = re.split(r"\n(?=## )", incoming_content)
    ext_headings = set(re.findall(r"^## (.+)$", existing_content, re.MULTILINE))

    new_sections = []
    for section in inc_sections:
        m = re.match(r"^## (.+)$", section, re.MULTILINE)
        if m and m.group(1) not in ext_headings:
            new_sections.append(section)

    if new_sections:
        merged = existing_content.rstrip() + "\n\n" + "\n".join(new_sections) + "\n"
        existing.write_text(merged, encoding="utf-8")
        logger.info("Merged %d new sections into %s", len(new_sections), existing.parent.name)


def _append_meta(path: Path, key: str, value: object) -> None:
    """Append a key-value to a YAML meta file."""
    meta = {}
    if path.exists():
        try:
            meta = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            meta = {}
    if key not in meta:
        meta[key] = value
    elif isinstance(meta[key], list):
        if value not in meta[key]:
            meta[key].append(value)
    else:
        meta[key] = [meta[key], value]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(meta, default_flow_style=False, allow_unicode=True))


def _log_decision(repo_path: Path, key: str, value: dict) -> None:
    """Log a manager decision to the decision log."""
    decisions_dir = repo_path / "agents"
    for agent_dir in decisions_dir.iterdir():
        identity = agent_dir / "identity.yaml"
        if identity.exists():
            try:
                ident = yaml.safe_load(identity.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError:
                continue
            if ident.get("role") == "manager":
                log_dir = agent_dir / "decisions"
                log_dir.mkdir(exist_ok=True)
                log_file = log_dir / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.yaml"
                _append_meta(log_file, key, value)
                return
