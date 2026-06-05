"""Tests for cli.py - Click CLI commands."""

from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from hermes_collective.cli import main, _ensure_profile_gateway_service, _use_profile


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

    def test_setup_creates_employee_crons_in_profile(self, runner, tmp_path):
        """Should create employee cron jobs during setup using the new profile."""
        join_result = {
            "local_path": str(tmp_path / "collective"),
            "installed_skills": ["employee-daily", "quality-pruning"],
            "cron_results": {"success": [], "failed": [], "skipped": []},
        }
        run_calls = []

        def fake_run(cmd, **kwargs):
            run_calls.append(cmd)
            return CompletedProcess(cmd, 0, stdout="", stderr="")

        with (
            patch("click.confirm", return_value=True),
            patch("hermes_collective.cli._run", side_effect=fake_run),
            patch("hermes_collective.cli.join_employee", return_value=join_result),
            patch("hermes_collective.cli._install_skills", return_value=[]),
            patch(
                "hermes_collective.cli._ensure_profile_gateway_service",
                return_value={"success": ["install", "start"], "failed": []},
            ) as gateway_service,
            patch(
                "hermes_collective.cli._create_crons",
                return_value={
                    "success": [
                        "collective-employee-alice",
                        "collective-sync-alice",
                        "collective-pruning-alice",
                    ],
                    "failed": [],
                    "skipped": [],
                },
            ) as create_crons,
        ):
            result = runner.invoke(
                main,
                ["setup"],
                input=f"employee\nalice\n{tmp_path / 'source'}\n17\n8\n",
            )

        assert result.exit_code == 0
        assert ["hermes", "profile", "use", "alice"] in run_calls
        gateway_service.assert_called_once_with("alice")
        create_crons.assert_called_once()
        kwargs = create_crons.call_args.kwargs
        assert kwargs["name"] == "alice"
        assert kwargs["role"] == "employee"
        assert kwargs["profile"] == "alice"
        assert kwargs["reflect_hour"] == 17
        assert kwargs["pull_hour"] == 8
        assert isinstance(kwargs["local_path"], Path)
        assert "Gateway service and cron jobs were configured in the Hermes profile" in result.output

    def test_setup_creates_manager_crons_in_profile(self, runner, tmp_path):
        """Should create manager cron jobs during setup using the new profile."""
        join_result = {
            "local_path": str(tmp_path / "collective"),
            "installed_skills": ["manager-cycle", "quality-pruning"],
            "cron_results": {"success": [], "failed": [], "skipped": []},
        }
        run_calls = []

        def fake_run(cmd, **kwargs):
            run_calls.append(cmd)
            return CompletedProcess(cmd, 0, stdout="", stderr="")

        with (
            patch("click.confirm", return_value=True),
            patch("hermes_collective.cli._run", side_effect=fake_run),
            patch("hermes_collective.cli.join_manager", return_value=join_result),
            patch("hermes_collective.cli._install_skills", return_value=[]),
            patch(
                "hermes_collective.cli._ensure_profile_gateway_service",
                return_value={"success": ["install", "start"], "failed": []},
            ) as gateway_service,
            patch(
                "hermes_collective.cli._create_crons",
                return_value={
                    "success": [
                        "collective-manager-overseer",
                        "collective-pruning-overseer",
                    ],
                    "failed": [],
                    "skipped": [],
                },
            ) as create_crons,
        ):
            result = runner.invoke(
                main,
                ["setup"],
                input=f"manager\noverseer\n{tmp_path / 'source'}\n21\n",
            )

        assert result.exit_code == 0
        assert ["hermes", "profile", "use", "overseer"] in run_calls
        gateway_service.assert_called_once_with("overseer")
        create_crons.assert_called_once()
        kwargs = create_crons.call_args.kwargs
        assert kwargs["name"] == "overseer"
        assert kwargs["role"] == "manager"
        assert kwargs["profile"] == "overseer"
        assert kwargs["manage_hour"] == 21
        assert "Gateway service and cron jobs were configured in the Hermes profile" in result.output

    def test_setup_reports_gateway_failure_without_blocking_crons(self, runner, tmp_path):
        """Should keep creating cron jobs if gateway service setup fails."""
        join_result = {
            "local_path": str(tmp_path / "collective"),
            "installed_skills": ["employee-daily", "quality-pruning"],
            "cron_results": {"success": [], "failed": [], "skipped": []},
        }

        with (
            patch("click.confirm", return_value=True),
            patch(
                "hermes_collective.cli._run",
                return_value=CompletedProcess(["hermes"], 0, stdout="", stderr=""),
            ),
            patch("hermes_collective.cli.join_employee", return_value=join_result),
            patch("hermes_collective.cli._install_skills", return_value=[]),
            patch(
                "hermes_collective.cli._ensure_profile_gateway_service",
                return_value={
                    "success": [],
                    "failed": [("install", "systemd unavailable")],
                },
            ),
            patch(
                "hermes_collective.cli._create_crons",
                return_value={
                    "success": ["collective-employee-alice"],
                    "failed": [],
                    "skipped": [],
                },
            ) as create_crons,
        ):
            result = runner.invoke(
                main,
                ["setup"],
                input=f"employee\nalice\n{tmp_path / 'source'}\n18\n0\n",
            )

        assert result.exit_code == 0
        create_crons.assert_called_once()
        assert "hermes -p alice gateway install" in result.output
        assert "profile gateway service needs attention" in result.output

    def test_setup_reports_profile_use_failure_without_blocking_setup(self, runner, tmp_path):
        """Should keep configuring gateway and cron jobs if profile switching fails."""
        join_result = {
            "local_path": str(tmp_path / "collective"),
            "installed_skills": ["employee-daily", "quality-pruning"],
            "cron_results": {"success": [], "failed": [], "skipped": []},
        }

        def fake_run(cmd, **kwargs):
            if cmd == ["hermes", "profile", "use", "alice"]:
                return CompletedProcess(cmd, 1, stdout="", stderr="cannot switch")
            return CompletedProcess(cmd, 0, stdout="", stderr="")

        with (
            patch("click.confirm", return_value=True),
            patch("hermes_collective.cli._run", side_effect=fake_run),
            patch("hermes_collective.cli.join_employee", return_value=join_result),
            patch("hermes_collective.cli._install_skills", return_value=[]),
            patch(
                "hermes_collective.cli._ensure_profile_gateway_service",
                return_value={"success": ["install", "start"], "failed": []},
            ),
            patch(
                "hermes_collective.cli._create_crons",
                return_value={
                    "success": ["collective-employee-alice"],
                    "failed": [],
                    "skipped": [],
                },
            ),
        ):
            result = runner.invoke(
                main,
                ["setup"],
                input=f"employee\nalice\n{tmp_path / 'source'}\n18\n0\n",
            )

        assert result.exit_code == 0
        assert "hermes profile use alice" in result.output
        assert "default profile switching failed" in result.output

    def test_ensure_profile_gateway_service_installs_and_starts(self):
        """Should install and start gateway service for the selected profile."""
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return CompletedProcess(cmd, 0, stdout="ok", stderr="")

        with patch("hermes_collective.cli._run", side_effect=fake_run):
            result = _ensure_profile_gateway_service("alice")

        assert result == {"success": ["install", "start"], "failed": []}
        assert calls == [
            ["hermes", "-p", "alice", "gateway", "install"],
            ["hermes", "-p", "alice", "gateway", "start"],
        ]

    def test_use_profile_switches_default_profile(self):
        """Should run Hermes profile use for the selected profile."""
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return CompletedProcess(cmd, 0, stdout="ok", stderr="")

        with patch("hermes_collective.cli._run", side_effect=fake_run):
            result = _use_profile("alice")

        assert result == {"success": True, "error": ""}
        assert calls == [["hermes", "profile", "use", "alice"]]


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
