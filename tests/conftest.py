"""
Test fixtures and helpers shared across all test modules.
"""

import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_repo():
    """
    Create a temporary directory with an initialized collective repo.

    Yields the repo path, cleans up after test.
    """
    tmp = tempfile.mkdtemp(prefix="hermes-collective-test-")
    repo_path = Path(tmp) / "collective"

    from hermes_collective.bootstrap import init_collective
    init_collective(name="test-team", repo_path=repo_path)

    yield repo_path

    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def temp_repo_with_employee(temp_repo):
    """
    Create a collective repo with one registered employee agent.
    """
    from hermes_collective.bootstrap import join_employee

    result = join_employee(
        name="alice",
        repo_url=str(temp_repo),
        local_path=temp_repo,
    )
    return temp_repo, result


@pytest.fixture
def temp_dir():
    """A clean temporary directory."""
    tmp = tempfile.mkdtemp(prefix="hermes-collective-test-")
    yield Path(tmp)
    shutil.rmtree(tmp, ignore_errors=True)
