"""
Tests for bootstrap.py — repo initialization, agent join, skill install.
"""

import yaml
from pathlib import Path

from hermes_collective.bootstrap import (
    init_collective,
    join_employee,
    join_manager,
    _install_skills,
    _safe_push,
)


class TestInitCollective:
    """Tests for init_collective()."""

    def test_creates_directory_structure(self, temp_dir):
        """Should create all required directories."""
        repo = temp_dir / "my-collective"

        result = init_collective(name="test-team", repo_path=repo)

        assert result == repo
        assert (repo / ".git").exists()
        assert (repo / "agents").is_dir()
        assert (repo / "skills" / "active").is_dir()
        assert (repo / "skills" / "staging").is_dir()
        assert (repo / "skills" / "archive").is_dir()
        assert (repo / "knowledge" / "active").is_dir()
        assert (repo / "knowledge" / "staging").is_dir()
        assert (repo / "knowledge" / "archive").is_dir()
        assert (repo / "failures" / "active").is_dir()
        assert (repo / "failures" / "staging").is_dir()
        assert (repo / "failures" / "archive").is_dir()
        assert (repo / "quality").is_dir()

    def test_creates_config(self, temp_dir):
        """Should create config.yaml with correct content."""
        repo = temp_dir / "my-collective"
        init_collective(name="test-team", repo_path=repo)

        config = yaml.safe_load((repo / "config.yaml").read_text())
        assert config["name"] == "test-team"
        assert config["version"] == 1
        assert "quality" in config
        assert config["quality"]["min_score"] == 0.3
        assert config["quality"]["archive_days"] == 60

    def test_creates_metrics(self, temp_dir):
        """Should create initial metrics.yaml."""
        repo = temp_dir / "my-collective"
        init_collective(name="test-team", repo_path=repo)

        assert (repo / "quality" / "metrics.yaml").exists()
        metrics = yaml.safe_load((repo / "quality" / "metrics.yaml").read_text())
        assert "agents" in metrics
        assert "skills" in metrics
        assert "knowledge" in metrics
        assert "failures" in metrics

    def test_fails_on_nonempty_dir(self, temp_dir):
        """Should raise FileExistsError if dir is not empty."""
        repo = temp_dir / "my-collective"
        repo.mkdir()
        (repo / "existing.txt").write_text("nope")

        import pytest
        with pytest.raises(FileExistsError, match="Directory not empty"):
            init_collective(name="test", repo_path=repo)

    def test_creates_initial_git_commit(self, temp_dir):
        """Should create repo with an initial commit."""
        repo = temp_dir / "my-collective"
        init_collective(name="test-team", repo_path=repo)

        import subprocess
        result = subprocess.run(
            ["git", "-C", str(repo), "log", "--oneline"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "Initialize" in result.stdout


class TestJoinEmployee:
    """Tests for join_employee()."""

    def test_creates_agent_identity(self, temp_repo):
        """Should create identity.yaml for the employee."""
        join_employee(
            name="alice",
            repo_url=str(temp_repo),
            local_path=temp_repo,
        )

        identity = yaml.safe_load(
            (temp_repo / "agents" / "alice" / "identity.yaml").read_text()
        )
        assert identity["name"] == "alice"
        assert identity["role"] == "employee"
        assert "joined" in identity

    def test_creates_inbox_directory(self, temp_repo):
        """Should create the inbox directory."""
        join_employee(name="alice", repo_url=str(temp_repo), local_path=temp_repo)

        assert (temp_repo / "agents" / "alice" / "inbox").is_dir()

    def test_installs_skills(self, temp_repo):
        """Should install employee-daily and quality-pruning skills."""
        result = join_employee(
            name="alice",
            repo_url=str(temp_repo),
            local_path=temp_repo,
        )

        assert "employee-daily" in result["installed_skills"]
        assert "quality-pruning" in result["installed_skills"]

    def test_compatible_with_already_cloned(self, temp_repo):
        """Should work even if repo is already cloned."""
        # First join
        join_employee(name="alice", repo_url=str(temp_repo), local_path=temp_repo)

        # Second join should not fail
        result = join_employee(
            name="alice",
            repo_url=str(temp_repo),
            local_path=temp_repo,
        )
        assert result is not None
        assert "installed_skills" in result

    def test_returns_correct_paths(self, temp_repo):
        """Should return correct paths in result dict."""
        result = join_employee(
            name="alice",
            repo_url=str(temp_repo),
            local_path=temp_repo,
        )

        assert "local_path" in result
        assert "agent_dir" in result
        assert "installed_skills" in result
        assert "sync_script" in result
        assert "next_steps" in result


class TestJoinManager:
    """Tests for join_manager()."""

    def test_creates_manager_identity(self, temp_repo):
        """Should create identity.yaml for the manager."""
        join_manager(
            name="overseer",
            repo_path=temp_repo,
            local_path=temp_repo,
        )

        identity = yaml.safe_load(
            (temp_repo / "agents" / "overseer" / "identity.yaml").read_text()
        )
        assert identity["name"] == "overseer"
        assert identity["role"] == "manager"

    def test_creates_decisions_directory(self, temp_repo):
        """Should create decisions/ directory for the manager."""
        join_manager(name="overseer", repo_path=temp_repo, local_path=temp_repo)

        assert (temp_repo / "agents" / "overseer" / "decisions").is_dir()

    def test_installs_manager_skills(self, temp_repo):
        """Should install manager-cycle and quality-pruning skills."""
        result = join_manager(
            name="overseer",
            repo_path=temp_repo,
            local_path=temp_repo,
        )

        assert "manager-cycle" in result["installed_skills"]
        assert "quality-pruning" in result["installed_skills"]


class TestInstallSkills:
    """Tests for _install_skills()."""

    def test_employee_skills(self, temp_dir):
        """Should install employee skills."""
        plugin_dir = Path(__file__).parent.parent / "hermes_collective" / "skills"

        installed = _install_skills(plugin_dir, temp_dir, role="employee")

        assert "employee-daily" in installed
        assert "quality-pruning" in installed
        assert "manager-cycle" not in installed

    def test_manager_skills(self, temp_dir):
        """Should install manager skills."""
        plugin_dir = Path(__file__).parent.parent / "hermes_collective" / "skills"

        installed = _install_skills(plugin_dir, temp_dir, role="manager")

        assert "manager-cycle" in installed
        assert "quality-pruning" in installed
        assert "employee-daily" not in installed

    def test_files_are_actually_copied(self, temp_dir):
        """Should copy actual SKILL.md files."""
        plugin_dir = Path(__file__).parent.parent / "hermes_collective" / "skills"

        _install_skills(plugin_dir, temp_dir, role="employee")

        assert (temp_dir / "collective" / "employee-daily" / "SKILL.md").exists()
        assert (temp_dir / "collective" / "quality-pruning" / "SKILL.md").exists()


class TestSafePush:
    """Tests for _safe_push()."""

    def test_no_remote_no_crash(self, temp_repo):
        """Should not crash when no remote is configured."""
        # temp_repo has no remote by default
        _safe_push(temp_repo, "alice", "employee")
        # No exception means pass
