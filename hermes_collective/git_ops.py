"""
Git operations for the collective — clone, pull, push, commit.

Uses GitPython for programmatic access with subprocess fallback.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Try GitPython first, fall back to subprocess
try:
    from git import Repo, InvalidGitRepositoryError, NoSuchPathError

    _USE_GITPYTHON = True
except ImportError:
    _USE_GITPYTHON = False
    logger.warning("GitPython not available, using subprocess fallback")


def _run_git(path: Path, *args: str) -> str:
    """Run a git command via subprocess."""
    import subprocess

    result = subprocess.run(
        ["git", "-C", str(path), *args],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


# ── High-level operations ──────────────────────────────────────────


def clone(repo_url: str, target: Path, branch: str = "main") -> Path:
    """Clone a collective repo. Returns the local path."""
    target = Path(target)
    if target.exists():
        raise FileExistsError(f"Target already exists: {target}")

    if _USE_GITPYTHON:
        Repo.clone_from(repo_url, str(target), branch=branch)
    else:
        _run_git(target.parent, "clone", "-b", branch, repo_url, str(target.name))

    logger.info("Cloned %s → %s", repo_url, target)
    return target


def pull(repo_path: Path) -> str:
    """Pull latest changes. Returns the pull summary."""
    # Check if remote exists before pulling
    import subprocess as _sp
    remote_check = _sp.run(
        ["git", "-C", str(repo_path), "remote", "get-url", "origin"],
        capture_output=True, text=True,
    )
    if remote_check.returncode != 0:
        logger.info("No remote 'origin' configured, skipping pull.")
        return "No remote configured."

    if _USE_GITPYTHON:
        repo = Repo(str(repo_path))
        origin = repo.remotes.origin
        result = origin.pull()
        return str(result[0].note) if result else "Already up to date."
    else:
        return _run_git(repo_path, "pull", "--ff-only")


def add_and_commit(repo_path: Path, message: str, files: list[str] | None = None) -> str:
    """Stage files and commit. Returns commit hash."""
    if _USE_GITPYTHON:
        repo = Repo(str(repo_path))
        if files:
            repo.git.add("--", *files)
        else:
            repo.git.add("-A")
        commit = repo.index.commit(message)
        return commit.hexsha
    else:
        if files:
            _run_git(repo_path, "add", "--", *files)
        else:
            _run_git(repo_path, "add", "-A")
        _run_git(repo_path, "commit", "-m", message)
        return _run_git(repo_path, "rev-parse", "HEAD")


def push(repo_path: Path) -> str:
    """Push commits to origin."""
    import subprocess as _sp

    remote_check = _sp.run(
        ["git", "-C", str(repo_path), "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
    )
    if remote_check.returncode != 0:
        logger.info("No remote 'origin' configured, skipping push.")
        return "No remote configured."

    if _USE_GITPYTHON:
        repo = Repo(str(repo_path))
        result = repo.remotes.origin.push()
        return str(result[0].summary) if result else "No push needed."
    else:
        return _run_git(repo_path, "push")


def status(repo_path: Path) -> str:
    """Get git status."""
    if _USE_GITPYTHON:
        repo = Repo(str(repo_path))
        return repo.git.status("--short")
    else:
        return _run_git(repo_path, "status", "--short")


def is_repo(path: Path) -> bool:
    """Check if path is a git repo."""
    if _USE_GITPYTHON:
        try:
            Repo(str(path))
            return True
        except (InvalidGitRepositoryError, NoSuchPathError):
            return False
    else:
        git_dir = path / ".git"
        return git_dir.exists() and git_dir.is_dir()


def init_repo(path: Path) -> Path:
    """Initialize a new git repo."""
    if _USE_GITPYTHON:
        Repo.init(str(path), initial_branch="main")
    else:
        _run_git(path, "init", "-b", "main")

    # Create initial .gitignore
    gitignore = path / ".gitignore"
    gitignore.write_text(
        "# Hermes Collective\n"
        ".DS_Store\n"
        "__pycache__/\n"
        "*.pyc\n"
        ".venv/\n"
        "*.swp\n"
        "*.swo\n"
        "*~\n"
    )
    return path
