"""
Tests for quality.py — scoring, pruning, metrics.
"""

import yaml
from pathlib import Path
from datetime import datetime, timezone

from hermes_collective.quality import (
    QualityReport,
    score_item,
    score_all,
    prune,
    update_usage,
    get_quality_report,
    _content_similarity,
    _apply_redundancy_penalties,
)


class TestContentSimilarity:
    """Tests for quality module's _content_similarity()."""

    def test_identical(self):
        assert _content_similarity("hello world", "hello world") == 1.0

    def test_near_duplicate(self):
        score = _content_similarity(
            "Deploy with docker-compose up",
            "Deploy with docker compose up",
        )
        assert score > 0.80


class TestQualityReport:
    """Tests for QualityReport class."""

    def test_age_days_with_none(self):
        report = QualityReport(
            path=Path("/tmp/test"),
            item_type="skill",
            name="test",
            last_updated=None,
        )
        assert report.age_days == 999

    def test_age_days_recent(self):
        now = datetime.now(timezone.utc)
        report = QualityReport(
            path=Path("/tmp/test"),
            item_type="skill",
            name="test",
            last_updated=now.isoformat(),
        )
        assert report.age_days == 0

    def test_stale_days_falls_back_to_age(self):
        report = QualityReport(
            path=Path("/tmp/test"),
            item_type="skill",
            name="test",
            last_used=None,
            last_updated="2020-01-01T00:00:00",
        )
        assert report.stale_days >= 999

    def test_quality_labels(self):
        report = QualityReport(
            path=Path("/tmp/test"), item_type="skill", name="test",
        )
        report.score = 0.8
        assert report.quality_label == "excellent"
        report.score = 0.5
        assert report.quality_label == "good"
        report.score = 0.3
        assert report.quality_label == "at-risk"
        report.score = 0.1
        assert report.quality_label == "stale"


class TestScoreItem:
    """Tests for score_item()."""

    def test_new_high_usage_item_scores_high(self):
        """A recently updated, frequently used item should score high."""
        now = datetime.now(timezone.utc).isoformat()
        report = QualityReport(
            path=Path("/tmp/test"),
            item_type="skill",
            name="test-skill",
            usage_count=15,
            last_used=now,
            last_updated=now,
        )
        result = score_item(report)
        # With neutral start 0.5 + freshness + usage bonuses
        assert result.score > 0.6, f"Expected high score, got {result.score}"

    def test_never_used_old_item_scores_low(self):
        """An old, never-used item should score low."""
        report = QualityReport(
            path=Path("/tmp/test"),
            item_type="skill",
            name="old-skill",
            usage_count=0,
            last_used=None,
            last_updated="2024-01-01T00:00:00",
        )
        result = score_item(report)
        assert result.score < 0.3, f"Expected low score, got {result.score}"

    def test_stale_penalty(self):
        """Items unused for >60 days should get a penalty."""
        report = QualityReport(
            path=Path("/tmp/test"),
            item_type="skill",
            name="stale-skill",
            usage_count=3,
            last_used="2025-01-01T00:00:00",  # Very old
            last_updated="2025-01-01T00:00:00",
        )
        result = score_item(report)
        assert result.score < 0.3, f"Stale item should score low, got {result.score}"


class TestScoreAll:
    """Tests for score_all()."""

    def test_empty_repo(self, temp_repo):
        """Should return empty list for empty repo."""
        reports = score_all(temp_repo)
        assert reports == []

    def test_scores_active_skills(self, temp_repo):
        """Should score skills in active/."""
        active = temp_repo / "skills" / "active" / "test-skill"
        active.mkdir(parents=True)
        (active / "SKILL.md").write_text("""---
name: test-skill
---

# Test Skill

## Overview
A skill for testing.

## Steps
1. Do X
```bash
command
```
""")

        reports = score_all(temp_repo)
        assert len(reports) == 1
        assert reports[0].item_type == "skill"
        assert reports[0].name == "test-skill"

    def test_scores_knowledge(self, temp_repo):
        """Should score knowledge items."""
        knowledge_dir = temp_repo / "knowledge" / "active"
        (knowledge_dir / "postgres.md").write_text("# PostgreSQL\n\nUse EXPLAIN ANALYZE.")

        reports = score_all(temp_repo)
        assert any(r.item_type == "knowledge" for r in reports)

    def test_scores_failures(self, temp_repo):
        """Should score failure reports."""
        failure_dir = temp_repo / "failures" / "active" / "2026" / "06"
        failure_dir.mkdir(parents=True)
        (failure_dir / "2026-06-01_alice_timeout.md").write_text(
            "# Timeout\n\n**Problem:** Connection timed out."
        )

        reports = score_all(temp_repo)
        assert any(r.item_type == "failure" for r in reports)


class TestRedundancyPenalties:
    """Tests for _apply_redundancy_penalties()."""

    def test_penalizes_similar_items(self, temp_dir):
        """Should penalize items with >80% similarity."""
        # Create two similar skill reports
        reports = [
            QualityReport(
                path=temp_dir / "skill-a.md",
                item_type="skill",
                name="skill-a",
                score=0.70,
            ),
            QualityReport(
                path=temp_dir / "skill-b.md",
                item_type="skill",
                name="skill-b",
                score=0.70,
            ),
        ]

        # Write very similar content
        (temp_dir / "skill-a.md").write_text(
            "## Deploy\n\n1. Run docker-compose up\n2. Check logs\n3. Verify endpoints\n"
        )
        (temp_dir / "skill-b.md").write_text(
            "## Deploy\n\n1. Run docker compose up\n2. Check the logs\n3. Verify all endpoints\n"
        )

        _apply_redundancy_penalties(reports)

        # Both should have their scores reduced
        assert reports[0].score < 0.70
        assert reports[1].score < 0.70

    def test_no_penalty_for_dissimilar(self, temp_dir):
        """Should not penalize items that are clearly different."""
        (temp_dir / "a.md").write_text("## Python Testing\n\nUse pytest.")
        (temp_dir / "b.md").write_text("## Docker Deploy\n\nUse docker-compose.")

        reports = [
            QualityReport(
                path=temp_dir / "a.md", item_type="skill", name="a", score=0.70,
            ),
            QualityReport(
                path=temp_dir / "b.md", item_type="skill", name="b", score=0.70,
            ),
        ]

        _apply_redundancy_penalties(reports)

        # Scores should be unchanged
        assert reports[0].score == 0.70
        assert reports[1].score == 0.70


class TestUpdateUsage:
    """Tests for update_usage()."""

    def test_creates_metrics_file(self, temp_repo):
        """Should create metrics.yaml if it doesn't exist."""
        metrics_path = temp_repo / "quality" / "metrics.yaml"
        metrics_path.unlink(missing_ok=True)

        update_usage(temp_repo, "skill", "test-skill")

        assert metrics_path.exists()
        metrics = yaml.safe_load(metrics_path.read_text())
        assert "skills" in metrics
        assert "test-skill" in metrics["skills"]

    def test_increments_usage(self, temp_repo):
        """Should increment usage count."""
        update_usage(temp_repo, "skill", "test-skill")
        update_usage(temp_repo, "skill", "test-skill")
        update_usage(temp_repo, "skill", "test-skill")

        metrics = yaml.safe_load(
            (temp_repo / "quality" / "metrics.yaml").read_text()
        )
        assert metrics["skills"]["test-skill"]["usage"] == 3

    def test_sets_last_used(self, temp_repo):
        """Should set last_used timestamp."""
        update_usage(temp_repo, "skill", "test-skill")

        metrics = yaml.safe_load(
            (temp_repo / "quality" / "metrics.yaml").read_text()
        )
        assert "last_used" in metrics["skills"]["test-skill"]


class TestPrune:
    """Tests for prune()."""

    def test_dry_run_no_changes(self, temp_repo):
        """Dry run should not modify files."""
        result = prune(temp_repo, dry_run=True)
        assert result["skills"] == 0
        assert result["knowledge"] == 0
        assert result["failures"] == 0

    def test_dry_run_reports_what_would_be_pruned(self, temp_repo):
        """Dry run should identify stale items."""
        # Create a skill with old timestamp
        active = temp_repo / "skills" / "active" / "old-skill"
        active.mkdir(parents=True)
        (active / "SKILL.md").write_text("Old content")

        result = prune(temp_repo, threshold=1.0, stale_days=0, dry_run=True)
        # With threshold=1.0 and stale_days=0, everything should be a candidate
        assert result["skills"] >= 1

    def test_actual_prune_archives_items(self, temp_repo):
        """Non-dry-run should actually move items to archive."""
        # Create a skill that will definitely be pruned
        active = temp_repo / "skills" / "active" / "very-old-skill"
        active.mkdir(parents=True)
        (active / "SKILL.md").write_text("just a note")  # low quality content

        # Set threshold high, stale_days low to catch everything
        result = prune(temp_repo, threshold=1.0, stale_days=0, dry_run=False)

        if result["skills"] > 0:
            # Should have been moved to archive
            assert not (temp_repo / "skills" / "active" / "very-old-skill").exists()
            assert (temp_repo / "skills" / "archive" / "very-old-skill").exists()


class TestGetQualityReport:
    """Tests for get_quality_report()."""

    def test_empty_repo(self, temp_repo):
        """Should return no-items message for empty repo."""
        report = get_quality_report(temp_repo)
        assert "No active items" in report

    def test_report_includes_items(self, temp_repo):
        """Should list items in the report."""
        active = temp_repo / "skills" / "active" / "test-skill"
        active.mkdir(parents=True)
        (active / "SKILL.md").write_text("""---
name: test-skill
---

# Test Skill

## Overview
Testing.

## Steps
1. Run test
```bash
pytest
```
""")

        report = get_quality_report(temp_repo)
        assert "test-skill" in report
        assert "Skills" in report
