"""
Quality scoring and pruning engine.

Tracks quality metrics for skills, knowledge, and failures.
Runs periodic pruning to archive low-quality, stale items.

Scoring dimensions:
- Usage: how often an item is loaded/referenced (tracked automatically)
- Freshness: how recently was it updated
- Structure: format quality (frontmatter, sections, code blocks)
- Completeness: has pitfalls, verification, prerequisites
- Redundancy: similarity to other items (lower overlap = better)
- Staleness: days since last used

Usage tracking is now automatic — update_usage() is called by aggregator
on promotion, and can be called via the CLI sync command when skills are
loaded by agents.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


# ── Naming helpers ─────────────────────────────────────────────────


def _metrics_section(item_type: str) -> str:
    """Return the metrics.yaml section for an item type."""
    return {
        "skill": "skills",
        "knowledge": "knowledge",
        "failure": "failures",
    }.get(item_type, item_type + "s")


def _pruned_key(item_type: str) -> str:
    """Return the prune result key for an item type."""
    return {
        "skill": "skills",
        "knowledge": "knowledge",
        "failure": "failures",
    }.get(item_type, item_type + "s")


# ── Similarity helpers ─────────────────────────────────────────────


def _content_similarity(a: str, b: str) -> float:
    """
    Compute content similarity using SequenceMatcher + Jaccard blend.

    Better than pure Jaccard (which was used before) because it catches
    near-duplicates with minor wording differences.
    """
    if not a.strip() or not b.strip():
        return 0.0
    sm = SequenceMatcher(None, a.lower(), b.lower()).ratio()
    a_words = set(a.lower().split())
    b_words = set(b.lower().split())
    if not a_words or not b_words:
        return sm
    jaccard = len(a_words & b_words) / len(a_words | b_words)
    return sm * 0.7 + jaccard * 0.3


# ── Data structures ────────────────────────────────────────────────


class QualityReport:
    """Quality assessment for a single item."""

    def __init__(
        self,
        path: Path,
        item_type: str,  # "skill", "knowledge", "failure"
        name: str,
        usage_count: int = 0,
        last_used: str | None = None,
        last_updated: str | None = None,
        score: float = 0.0,
        issues: list[str] | None = None,
    ):
        self.path = path
        self.item_type = item_type
        self.name = name
        self.usage_count = usage_count
        self.last_used = last_used
        self.last_updated = last_updated
        self.score = score
        self.issues = issues or []

    @property
    def age_days(self) -> int:
        """Days since last update."""
        if not self.last_updated:
            return 999
        try:
            updated = datetime.fromisoformat(self.last_updated)
            return (datetime.now(timezone.utc) - updated).days
        except (ValueError, TypeError):
            return 999

    @property
    def stale_days(self) -> int:
        """Days since last used."""
        if not self.last_used:
            return self.age_days  # fall back to age
        try:
            used = datetime.fromisoformat(self.last_used)
            return (datetime.now(timezone.utc) - used).days
        except (ValueError, TypeError):
            return self.age_days

    @property
    def quality_label(self) -> str:
        """Human-readable quality label."""
        if self.score >= 0.7:
            return "excellent"
        elif self.score >= 0.4:
            return "good"
        elif self.score >= 0.2:
            return "at-risk"
        else:
            return "stale"


# ── Scoring engine ─────────────────────────────────────────────────


def score_item(item: QualityReport, config: dict | None = None) -> QualityReport:
    """
    Compute a quality score (0.0–1.0) for an item.

    Multi-dimensional scoring:
    - Freshness (25%): newer items score higher
    - Usage (25%): frequently loaded items score higher
    - Staleness (20%): penalize items unused for extended periods
    - Structure (20%): format quality (frontmatter, sections, code)
    - Redundancy (10%): not yet implemented at single-item level,
      handled at the batch level via similarity checks

    Config overrides from collective config.yaml (quality section).
    (Reserved for future use.)
    """
    score = 0.5  # Start neutral

    # ── 1. Freshness (25%) ──
    if item.age_days < 7:
        score += 0.20
    elif item.age_days < 30:
        score += 0.10
    elif item.age_days > 90:
        score -= 0.25
        item.issues.append(f"Stale: not updated in {item.age_days} days")

    # ── 2. Usage (25%) ──
    if item.usage_count > 10:
        score += 0.20
    elif item.usage_count > 5:
        score += 0.15
    elif item.usage_count > 3:
        score += 0.10
    elif item.usage_count == 0:
        score -= 0.15
        item.issues.append("Never used — consider archiving")

    # ── 3. Staleness (20%) ──
    if item.stale_days > 60:
        score -= 0.25
        item.issues.append(f"Unused for {item.stale_days} days")
    elif item.stale_days > 30:
        score -= 0.12
        item.issues.append(f"Unused for {item.stale_days} days")

    # ── 4. Structure (20%) — content-based ──
    if item.path.exists() and item.item_type in ("skill", "knowledge"):
        try:
            content = item.path.read_text(encoding="utf-8")
        except Exception:
            content = ""

        if content.startswith("---"):
            score += 0.06
        if "## " in content:
            score += 0.05
        if "```" in content:
            score += 0.05
        if len(content) > 200:
            score += 0.04

        # Extra for skills: completeness checks
        if item.item_type == "skill":
            if "pitfall" in content.lower():
                score += 0.04
            if "verification" in content.lower() or "checklist" in content.lower():
                score += 0.04

        # Low-content penalty
        if len(content) < 100:
            score -= 0.10
            item.issues.append("Very short — may be incomplete")

    # ── 5. Redundancy (10%) — batch-level check done in score_all() ──

    item.score = max(0.0, min(1.0, round(score, 2)))
    return item


def score_all(repo_path: Path, config: dict | None = None) -> list[QualityReport]:
    """Score all active items in the collective."""
    reports: list[QualityReport] = []

    # Load usage metrics
    metrics = _load_metrics(repo_path)

    # Score active skills
    skills_dir = repo_path / "skills" / "active"
    if skills_dir.exists():
        for skill_dir in skills_dir.iterdir():
            if not skill_dir.is_dir():
                continue
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                continue
            skill_metrics = metrics.get("skills", {}).get(skill_dir.name, {})
            report = QualityReport(
                path=skill_file,
                item_type="skill",
                name=skill_dir.name,
                usage_count=skill_metrics.get("usage", 0),
                last_used=skill_metrics.get("last_used"),
                last_updated=skill_metrics.get("last_updated"),
            )
            reports.append(score_item(report, config))

    # Score active knowledge
    knowledge_dir = repo_path / "knowledge" / "active"
    if knowledge_dir.exists():
        for kfile in knowledge_dir.glob("*.md"):
            if kfile.name == ".gitkeep":
                continue
            km = {
                **metrics.get("knowledges", {}),
                **metrics.get("knowledge", {}),
            }.get(kfile.stem, {})
            report = QualityReport(
                path=kfile,
                item_type="knowledge",
                name=kfile.stem,
                usage_count=km.get("usage", 0),
                last_used=km.get("last_used"),
                last_updated=km.get("last_updated"),
            )
            reports.append(score_item(report, config))

    # Score active failures
    failures_dir = repo_path / "failures" / "active"
    if failures_dir.exists():
        for ffile in failures_dir.rglob("*.md"):
            if ffile.name == ".gitkeep":
                continue
            rel = str(ffile.relative_to(failures_dir))
            fm = metrics.get("failures", {}).get(rel, {})
            report = QualityReport(
                path=ffile,
                item_type="failure",
                name=rel,
                usage_count=fm.get("usage", 0),
                last_used=fm.get("last_used"),
                last_updated=fm.get("last_updated"),
            )
            reports.append(score_item(report, config))

    # ── Redundancy scoring (cross-item) ──
    _apply_redundancy_penalties(reports)

    return reports


def _apply_redundancy_penalties(reports: list[QualityReport]) -> None:
    """
    Detect redundancy between items of the same type and penalize both.

    For each pair of same-type items with high content similarity,
    both get a small penalty (having near-duplicates degrades the
    overall quality of the knowledge base).
    """
    # Group by type
    by_type: dict[str, list[QualityReport]] = {}
    for r in reports:
        by_type.setdefault(r.item_type, []).append(r)

    for items in by_type.values():
        if len(items) < 2:
            continue

        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                a, b = items[i], items[j]
                if not a.path.exists() or not b.path.exists():
                    continue

                try:
                    content_a = a.path.read_text(encoding="utf-8")
                    content_b = b.path.read_text(encoding="utf-8")
                except Exception:
                    continue

                sim = _content_similarity(content_a, content_b)
                if sim > 0.80:
                    # Both get a small redundancy penalty
                    penalty = (sim - 0.80) * 0.50  # Max penalty ~0.10
                    a.score = max(0.0, round(a.score - penalty, 2))
                    b.score = max(0.0, round(b.score - penalty, 2))
                    msg = f"Redundant with '{b.name}' (similarity: {sim:.0%})"
                    if msg not in a.issues:
                        a.issues.append(msg)
                    msg = f"Redundant with '{a.name}' (similarity: {sim:.0%})"
                    if msg not in b.issues:
                        b.issues.append(msg)


# ── Pruning ────────────────────────────────────────────────────────


def prune(
    repo_path: Path,
    threshold: float = 0.3,
    stale_days: int = 60,
    dry_run: bool = True,
) -> dict:
    """
    Prune low-quality, stale items.

    Items below threshold AND stale beyond stale_days are archived.

    Returns dict with pruned item counts by category.
    """
    config = _load_config(repo_path)
    threshold = config.get("quality", {}).get("min_score", threshold)
    stale_days = config.get("quality", {}).get("archive_days", stale_days)

    reports = score_all(repo_path, config)
    to_prune = [
        r for r in reports
        if r.score < threshold and r.stale_days > stale_days
    ]

    pruned = {"skills": 0, "knowledge": 0, "failures": 0}

    for item in to_prune:
        if dry_run:
            logger.info(
                "[DRY RUN] Would archive: %s (%s, score=%.2f, stale=%d days, issues=%s)",
                item.name, item.item_type, item.score, item.stale_days,
                item.issues,
            )
        else:
            _archive_item(repo_path, item)

        pruned[_pruned_key(item.item_type)] += 1

    # Log pruning decisions
    if not dry_run and to_prune:
        _log_pruning(repo_path, to_prune)

    return pruned


def _archive_item(repo_path: Path, item: QualityReport) -> None:
    """Move an item from active to archive."""
    archive_base = repo_path / _archive_dir(item.item_type)
    archive_base.mkdir(parents=True, exist_ok=True)

    if item.item_type == "skill":
        src = item.path.parent  # the skill directory
        dst = archive_base / item.name
    else:
        src = item.path
        dst = archive_base / item.path.name

    if src.exists():
        import shutil

        if dst.exists():
            shutil.rmtree(dst) if dst.is_dir() else dst.unlink()
        shutil.move(str(src), str(dst))
        logger.info("Archived: %s → %s", item.name, dst.relative_to(repo_path))


def _archive_dir(item_type: str) -> str:
    return {
        "skill": "skills/archive",
        "knowledge": "knowledge/archive",
        "failure": "failures/archive",
    }.get(item_type, f"{item_type}s/archive")


# ── Metrics persistence ───────────────────────────────────────────


def update_usage(repo_path: Path, item_type: str, item_name: str) -> None:
    """
    Record a usage event for an item.

    Called automatically by:
    - aggregator.py on skill promotion
    - cli.py sync command when syncing skills
    - Can be called externally for manual tracking
    """
    metrics = _load_metrics(repo_path)
    now = datetime.now(timezone.utc).isoformat()

    section = metrics.setdefault(_metrics_section(item_type), {})
    entry = section.setdefault(item_name, {})
    entry["usage"] = entry.get("usage", 0) + 1
    entry["last_used"] = now

    # Auto-set last_updated if not present
    if "last_updated" not in entry:
        entry["last_updated"] = now

    _save_metrics(repo_path, metrics)


def bulk_update_usage(repo_path: Path, item_type: str, item_names: list[str]) -> None:
    """Record usage for multiple items at once (e.g., on sync)."""
    for name in item_names:
        update_usage(repo_path, item_type, name)


def _load_metrics(repo_path: Path) -> dict:
    path = repo_path / "quality" / "metrics.yaml"
    if path.exists():
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {}


def _save_metrics(repo_path: Path, metrics: dict) -> None:
    path = repo_path / "quality" / "metrics.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(metrics, default_flow_style=False, allow_unicode=True))


def _load_config(repo_path: Path) -> dict:
    config_path = repo_path / "config.yaml"
    if config_path.exists():
        return yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return {}


def _log_pruning(repo_path: Path, pruned: list[QualityReport]) -> None:
    """Append pruning decisions to the log."""
    log_path = repo_path / "quality" / "pruning-log.yaml"
    now = datetime.now(timezone.utc).isoformat()

    log = {}
    if log_path.exists():
        log = yaml.safe_load(log_path.read_text(encoding="utf-8")) or {}

    log[now] = {
        "action": "prune",
        "count": len(pruned),
        "items": [
            {
                "name": p.name,
                "type": p.item_type,
                "score": p.score,
                "stale_days": p.stale_days,
                "issues": p.issues,
            }
            for p in pruned
        ],
    }

    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(yaml.dump(log, default_flow_style=False, allow_unicode=True))


# ── Command helpers ────────────────────────────────────────────────


def get_quality_report(repo_path: Path) -> str:
    """Generate a human-readable quality report."""
    reports = score_all(repo_path)

    if not reports:
        return "No active items to report on."

    by_type: dict[str, list[QualityReport]] = {}
    for r in reports:
        by_type.setdefault(r.item_type, []).append(r)

    lines = ["=== Quality Report ===", ""]
    for item_type, items in sorted(by_type.items()):
        lines.append(f"## {item_type.capitalize()}s ({len(items)})")
        avg_score = sum(i.score for i in items) / len(items) if items else 0

        # Distribution
        excellent = sum(1 for i in items if i.score >= 0.7)
        good = sum(1 for i in items if 0.4 <= i.score < 0.7)
        at_risk = sum(1 for i in items if 0.2 <= i.score < 0.4)
        stale = sum(1 for i in items if i.score < 0.2)

        lines.append(f"   Average: {avg_score:.2f}")
        lines.append(
            f"   Distribution: {excellent} excellent, {good} good, "
            f"{at_risk} at-risk, {stale} stale"
        )
        lines.append("")

        # Show top 3 and bottom 3
        sorted_items = sorted(items, key=lambda x: x.score, reverse=True)
        lines.append("   Top:")
        for r in sorted_items[:3]:
            lines.append(
                f"     {r.score:.2f} [{r.quality_label}] {r.name}  "
                f"(used {r.usage_count}x, {r.age_days}d old)"
            )
        if len(sorted_items) > 3:
            lines.append("   Bottom:")
            for r in sorted_items[-3:]:
                lines.append(
                    f"     {r.score:.2f} [{r.quality_label}] {r.name}  "
                    f"(used {r.usage_count}x, {r.stale_days}d stale)"
                )
                if r.issues:
                    for issue in r.issues:
                        lines.append(f"       ⚠ {issue}")
        lines.append("")

    return "\n".join(lines)
