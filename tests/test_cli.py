"""Tests for cli.py - Click CLI commands."""

from unittest.mock import patch

import pytest
from click.testing import CliRunner

from hermes_collective.cli import main


@pytest.fixture
def runner():
    """Click CLI test runner."""
    return CliRunner()


class TestCLIVersion:
    """Tests for CLI version output."""

    def test_version(self, runner):
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "hermes-collective" in result.output


class TestCLISetup:
    """Tests for setup wizard."""

    def test_setup_abort(self, runner):
        """Should handle abort (typing 'n' at confirmation)."""
        with patch("click.confirm", return_value=False):
            result = runner.invoke(main, ["setup"], input="employee\nalice\n/repo/dummy\n")
            assert result.exit_code == 0
            assert "Aborted" in result.output or result.exit_code == 0

    def test_setup_default_employee(self, runner):
        """Should work with default inputs."""
        with patch("click.confirm", return_value=False):
            result = runner.invoke(main, ["setup"], input="\n\n\n\n")
            assert result.exit_code == 0


class TestCLIInit:
    """Tests for init command."""

    def test_init_basic(self, runner, tmp_path):
        """Should initialize a collective repo."""
        repo_path = tmp_path / "test-collective"
        result = runner.invoke(main, ["init", "--name", "my-team", "--repo", str(repo_path)])
        assert result.exit_code == 0
        assert (repo_path / ".git").exists()

    def test_init_fails_on_nonempty(self, runner, tmp_path):
        """Should fail if directory is not empty."""
        repo_path = tmp_path / "existing"
        repo_path.mkdir()
        (repo_path / "somefile.txt").write_text("data")
        result = runner.invoke(main, ["init", "--name", "test", "--repo", str(repo_path)])
        assert result.exit_code != 0

    def test_init_bare_repo(self, runner, tmp_path):
        """Should create a bare repo."""
        repo_path = tmp_path / "bare-collective"
        result = runner.invoke(main, ["init", "--name", "server", "--repo", str(repo_path), "--bare"])
        assert result.exit_code == 0
        assert (repo_path / "HEAD").exists()


class TestCLIJoin:
    """Tests for join command."""

    def test_join_employee(self, runner, tmp_path):
        """Should register an employee agent."""
        repo_path = tmp_path / "collective"
        runner.invoke(main, ["init", "--name", "test", "--repo", str(repo_path)])
        result = runner.invoke(main, [
            "join", "--name", "alice", "--repo", str(repo_path),
            "--role", "employee", "--path", str(repo_path),
        ])
        assert result.exit_code == 0
        assert (repo_path / "agents" / "alice" / "identity.yaml").exists()

    def test_join_manager(self, runner, tmp_path):
        """Should register a manager agent."""
        repo_path = tmp_path / "collective"
        runner.invoke(main, ["init", "--name", "test", "--repo", str(repo_path)])
        result = runner.invoke(main, [
            "join", "--name", "overseer", "--repo", str(repo_path),
            "--role", "manager", "--path", str(repo_path),
        ])
        assert result.exit_code == 0
        assert (repo_path / "agents" / "overseer" / "identity.yaml").exists()


class TestCLIRun:
    """Tests for run command."""

    def test_run_requires_role(self, runner):
        """Should fail without --role."""
        result = runner.invoke(main, ["run"])
        assert result.exit_code != 0

    def test_run_manager_dry(self, runner, tmp_path):
        """Should run manager workflow in dry-run mode."""
        repo_path = tmp_path / "collective"
        runner.invoke(main, ["init", "--name", "test", "--repo", str(repo_path)])
        result = runner.invoke(main, [
            "run", "--role", "manager", "--repo", str(repo_path), "--dry-run",
        ])
        assert result.exit_code == 0

    def test_run_employee(self, runner, tmp_path):
        """Should run employee workflow."""
        repo_path = tmp_path / "collective"
        runner.invoke(main, ["init", "--name", "test", "--repo", str(repo_path)])
        runner.invoke(main, [
            "join", "--name", "alice", "--repo", str(repo_path),
            "--role", "employee", "--path", str(repo_path),
        ])
        result = runner.invoke(main, [
            "run", "--role", "employee", "--repo", str(repo_path), "--name", "alice",
        ])
        assert result.exit_code == 0


class TestCLIStatus:
    """Tests for status command."""

    def test_status_empty_repo(self, runner, tmp_path):
        """Should show status for empty repo."""
        repo_path = tmp_path / "collective"
        runner.invoke(main, ["init", "--name", "test", "--repo", str(repo_path)])
        result = runner.invoke(main, ["status", "--repo", str(repo_path)])
        assert result.exit_code == 0

    def test_status_with_agents(self, runner, tmp_path):
        """Should show agents when registered."""
        repo_path = tmp_path / "collective"
        runner.invoke(main, ["init", "--name", "test", "--repo", str(repo_path)])
        runner.invoke(main, [
            "join", "--name", "alice", "--repo", str(repo_path),
            "--role", "employee", "--path", str(repo_path),
        ])
        result = runner.invoke(main, ["status", "--repo", str(repo_path)])
        assert result.exit_code == 0
        assert "alice" in result.output

    def test_status_nonexistent_repo(self, runner):
        """Should fail if repo doesn't exist."""
        result = runner.invoke(main, ["status", "--repo", "/nonexistent/path"])
        assert result.exit_code != 0


class TestCLIPrune:
    """Tests for prune-cmd."""

    def test_prune_dry_run(self, runner, tmp_path):
        """Should do dry-run pruning."""
        repo_path = tmp_path / "collective"
        runner.invoke(main, ["init", "--name", "test", "--repo", str(repo_path)])
        result = runner.invoke(main, ["prune-cmd", "--repo", str(repo_path), "--dry-run"])
        assert result.exit_code == 0


class TestCLISync:
    """Tests for sync command."""

    def test_sync_empty_repo(self, runner, tmp_path):
        """Should sync from empty repo."""
        repo_path = tmp_path / "collective"
        runner.invoke(main, ["init", "--name", "test", "--repo", str(repo_path)])
        result = runner.invoke(main, ["sync", "--repo", str(repo_path)])
        assert result.exit_code == 0


class TestHelpOutput:
    """Tests for help output."""

    def test_main_help(self, runner):
        """Should show main help."""
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "Hermes Collective" in result.output

    def test_subcommand_help(self, runner):
        """Should show help for subcommands."""
        for cmd in ["init", "join", "run", "status", "prune-cmd", "sync", "setup"]:
            result = runner.invoke(main, [cmd, "--help"])
            assert result.exit_code == 0, f"Help for '{cmd}' failed"
