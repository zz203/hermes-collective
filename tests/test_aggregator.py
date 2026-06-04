"""
Tests for aggregator.py — tool functions for collective repository operations.

Tests the scanner, reader, writer, git, and quality functions that
subagents call via execute_code.
"""


from hermes_collective.aggregator import (
    # Scanner
    scan_inboxes,
    scan_staging_skills,
    scan_active_skills,
    # Reader
    read_inbox,
    read_skill,
    get_existing_knowledge,
    promote_skill,
    keep_skill_in_staging,
    reject_skill,
    merge_skills,
    write_knowledge,
    write_failure,
    clean_inbox,
    clean_all_inboxes,
    # Git
    commit_changes,
    # Internal helpers
    _content_similarity,
    _merge_skill_md,
)


class TestContentSimilarity:
    """Tests for _content_similarity()."""

    def test_identical(self):
        assert _content_similarity("hello world", "hello world") == 1.0

    def test_completely_different(self):
        score = _content_similarity("hello world", "python code")
        assert score < 0.3

    def test_near_duplicate_typo(self):
        score = _content_similarity(
            "## Overview\nInstall the package with pip.",
            "## Overview\nInstall the packge with pip.",
        )
        assert score > 0.80

    def test_empty_strings(self):
        assert _content_similarity("", "") == 0.0
        assert _content_similarity("text", "") == 0.0


class TestMergeSkillMd:
    """Tests for _merge_skill_md()."""

    def test_appends_new_sections(self, tmp_path):
        existing = tmp_path / "existing.md"
        existing.write_text("""# Skill

## Overview
Old content.

## Steps
1. Old step
""")
        incoming = tmp_path / "incoming.md"
        incoming.write_text("""# Skill

## Overview
New content.

## Pitfalls
- New pitfall

## Verification
- New check
""")

        _merge_skill_md(existing, incoming)
        merged = existing.read_text()

        assert "Pitfalls" in merged
        assert "Verification" in merged
        assert "Old content" in merged  # Original preserved

    def test_no_duplicate_sections(self, tmp_path):
        existing = tmp_path / "existing.md"
        existing.write_text("## Steps\n1. Step one\n")
        incoming = tmp_path / "incoming.md"
        incoming.write_text("## Steps\n1. Different step\n## Pitfalls\n- Watch out\n")

        _merge_skill_md(existing, incoming)
        merged = existing.read_text()

        # Steps should NOT be duplicated
        assert merged.count("## Steps") == 1
        # Pitfalls should be added
        assert "Pitfalls" in merged


class TestScanInboxes:
    """Tests for scan_inboxes()."""

    def test_empty_repo(self, temp_repo):
        items = scan_inboxes(temp_repo)
        assert items == []

    def test_collects_inbox_files(self, temp_repo):
        agent_dir = temp_repo / "agents" / "alice" / "inbox"
        agent_dir.mkdir(parents=True)
        (agent_dir / "2026-06-01.md").write_text("# Report\n\nSome content.")

        items = scan_inboxes(temp_repo)
        assert len(items) == 1
        assert items[0]["agent"] == "alice"
        assert items[0]["date"] == "2026-06-01"

    def test_collects_multiple_agents(self, temp_repo):
        for agent in ["alice", "bob"]:
            agent_dir = temp_repo / "agents" / agent / "inbox"
            agent_dir.mkdir(parents=True)
            (agent_dir / "2026-06-01.md").write_text(f"Report from {agent}")

        items = scan_inboxes(temp_repo)
        assert len(items) == 2

    def test_skips_empty_files(self, temp_repo):
        agent_dir = temp_repo / "agents" / "alice" / "inbox"
        agent_dir.mkdir(parents=True)
        (agent_dir / "2026-06-01.md").write_text("")

        items = scan_inboxes(temp_repo)
        assert len(items) == 0


class TestScanStaging:
    """Tests for scan_staging_skills()."""

    def test_empty_staging(self, temp_repo):
        skills = scan_staging_skills(temp_repo)
        assert skills == []

    def test_lists_staging_skills(self, temp_repo):
        staging = temp_repo / "skills" / "staging" / "candidate-test"
        staging.mkdir(parents=True)
        (staging / "SKILL.md").write_text("# Test skill")

        skills = scan_staging_skills(temp_repo)
        assert len(skills) == 1
        assert skills[0]["name"] == "candidate-test"


class TestScanActive:
    """Tests for scan_active_skills()."""

    def test_empty_active(self, temp_repo):
        skills = scan_active_skills(temp_repo)
        assert skills == []

    def test_lists_active_skills(self, temp_repo):
        active = temp_repo / "skills" / "active" / "test-skill"
        active.mkdir(parents=True)
        (active / "SKILL.md").write_text("# Test")

        skills = scan_active_skills(temp_repo)
        assert len(skills) == 1


class TestReadInbox:
    """Tests for read_inbox()."""

    def test_parses_sections(self, temp_repo):
        inbox_file = temp_repo / "agents" / "alice" / "inbox" / "2026-06-01.md"
        inbox_file.parent.mkdir(parents=True)
        inbox_file.write_text("""# Report

## What I Worked On
Did some work.

## Knowledge
- Fact about PostgreSQL.
- Use EXPLAIN ANALYZE.

## Failures
- **Problem:** Timeout
- **Fix:** Increased timeout
""")

        data = read_inbox(str(inbox_file))
        assert data["agent"] == "alice"
        assert data["date"] == "2026-06-01"
        assert "knowledge" in data["sections"]
        assert "PostgreSQL" in data["sections"]["knowledge"]
        assert "failures" in data["sections"]
        assert "Timeout" in data["sections"]["failures"]


class TestReadSkill:
    """Tests for read_skill()."""

    def test_reads_frontmatter(self, temp_repo):
        skill_file = temp_repo / "skills" / "staging" / "test-skill" / "SKILL.md"
        skill_file.parent.mkdir(parents=True)
        skill_file.write_text("""---
name: test-skill
version: 1.0.0
---

# Test Skill

## Overview
A test skill.
""")

        skill = read_skill(str(skill_file))
        assert skill["name"] == "test-skill"
        assert skill["frontmatter"]["name"] == "test-skill"
        assert skill["frontmatter"]["version"] == "1.0.0"
        assert "Overview" in skill["content"]


class TestKnowledgeOperations:
    """Tests for write_knowledge and get_existing_knowledge."""

    def test_write_and_read_knowledge(self, temp_repo):
        result = write_knowledge(
            temp_repo, "postgresql",
            "PostgreSQL uses MVCC for concurrency control.",
            source_agent="alice", source_date="2026-06-01",
        )
        assert result["action"] == "written"

        knowledge = get_existing_knowledge(temp_repo, "postgresql")
        assert "MVCC" in knowledge["content"]["postgresql"]

    def test_duplicate_detection(self, temp_repo):
        content = "PostgreSQL uses MVCC for concurrency control."
        write_knowledge(temp_repo, "postgresql", content)
        result = write_knowledge(
            temp_repo, "postgresql", content,
            check_duplicate=True,
        )
        assert result["action"] == "skipped"

    def test_list_all_topics(self, temp_repo):
        write_knowledge(temp_repo, "docker", "Docker tip.")
        write_knowledge(temp_repo, "python", "Python tip.")

        knowledge = get_existing_knowledge(temp_repo)
        assert "docker" in knowledge["topics"]
        assert "python" in knowledge["topics"]


class TestFailureOperations:
    """Tests for write_failure and get_existing_failures."""

    def test_write_failure(self, temp_repo):
        result = write_failure(
            temp_repo,
            "Connection timeout when deploying to production.\n\n## Fix\nIncreased timeout to 30s.",
            source_agent="alice", date="2026-06-01",
        )
        assert result["action"] == "written"

    def test_duplicate_failure(self, temp_repo):
        content = "Connection timeout when deploying."
        write_failure(temp_repo, content, source_agent="alice", date="2026-06-01")
        result = write_failure(
            temp_repo, content,
            source_agent="bob", date="2026-06-02",
            check_duplicate=True,
        )
        assert result["action"] in ("merged", "written")  # Either is acceptable


class TestPromoteSkill:
    """Tests for promote_skill()."""

    def test_promotes_to_active(self, temp_repo):
        staging = temp_repo / "skills" / "staging" / "test-skill"
        staging.mkdir(parents=True)
        (staging / "SKILL.md").write_text("""---
name: test-skill
---

# Test Skill

## Overview
Test.

## Steps
1. Do X
```bash
command
```

## Pitfalls
- Issue

## Verification
- [ ] Done
""")

        result = promote_skill(temp_repo, "test-skill", score=0.7)
        assert result["action"] in ("promoted", "merged")

        # Should be in active
        assert (temp_repo / "skills" / "active" / "test-skill" / "SKILL.md").exists()
        # Should NOT be in staging anymore
        assert not staging.exists()

    def test_nonexistent_skill(self, temp_repo):
        result = promote_skill(temp_repo, "nonexistent")
        assert "error" in result


class TestRejectSkill:
    """Tests for reject_skill()."""

    def test_rejects_and_logs(self, temp_repo):
        staging = temp_repo / "skills" / "staging" / "bad-skill"
        staging.mkdir(parents=True)
        (staging / "SKILL.md").write_text("Just restart it.")

        result = reject_skill(temp_repo, "bad-skill", "Too trivial")
        assert result["action"] == "rejected"
        assert not staging.exists()


class TestKeepSkill:
    """Tests for keep_skill_in_staging()."""

    def test_keeps_with_note(self, temp_repo):
        staging = temp_repo / "skills" / "staging" / "medium-skill"
        staging.mkdir(parents=True)
        (staging / "SKILL.md").write_text("# Skill content")

        result = keep_skill_in_staging(temp_repo, "medium-skill", "Needs more steps")
        assert result["action"] == "kept"
        assert staging.exists()


class TestMergeSkills:
    """Tests for merge_skills()."""

    def test_merges_two_skills(self, temp_repo):
        # Create source in staging
        src = temp_repo / "skills" / "staging" / "source-skill"
        src.mkdir(parents=True)
        (src / "SKILL.md").write_text("## Steps\n1. Source step\n## Pitfalls\n- Source pitfall\n")

        # Create target in active
        tgt = temp_repo / "skills" / "active" / "target-skill"
        tgt.mkdir(parents=True)
        (tgt / "SKILL.md").write_text("## Steps\n1. Target step\n## Overview\nTarget overview\n")

        result = merge_skills(temp_repo, "source-skill", "target-skill")
        assert result["action"] == "merged"

        merged_content = (tgt / "SKILL.md").read_text()
        assert "Pitfalls" in merged_content  # New section from source


class TestCleanInboxes:
    """Tests for clean_inbox and clean_all_inboxes."""

    def test_clean_single_inbox(self, temp_repo):
        inbox_file = temp_repo / "agents" / "alice" / "inbox" / "2026-06-01.md"
        inbox_file.parent.mkdir(parents=True)
        inbox_file.write_text("# Report")

        result = clean_inbox(temp_repo, "alice", "2026-06-01")
        assert result["action"] == "cleaned"
        assert not inbox_file.exists()

    def test_clean_all_inboxes(self, temp_repo):
        for agent in ["alice", "bob"]:
            inbox_file = temp_repo / "agents" / agent / "inbox" / "2026-06-01.md"
            inbox_file.parent.mkdir(parents=True)
            inbox_file.write_text(f"Report from {agent}")

        result = clean_all_inboxes(temp_repo)
        assert result["count"] == 2


class TestCommitChanges:
    """Tests for commit_changes()."""

    def test_commits_changes(self, temp_repo):
        (temp_repo / "test-file.md").write_text("new content")

        result = commit_changes(temp_repo, "Test commit")
        assert result["action"] == "committed"
