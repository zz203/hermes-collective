# Repository Guidelines

## Project Structure & Module Organization

This is a Python package for Hermes Collective. Core implementation lives in
`hermes_collective/`:

| Module | Role |
|--------|------|
| `cli.py` | Click CLI: `init`, `join`, `run`, `prune`, `status`, `sync`, `setup` |
| `bootstrap.py` | Repo init, agent join (employee/manager), skill install, cron auto-creation |
| `aggregator.py` | **Tool function library** — scanner, reader, writer, git helpers. Called by subagents via `execute_code`. No intelligence here; that lives in skills. |
| `quality.py` | Scoring engine, pruning, usage metrics, quality reports |
| `git_ops.py` | Git operations (GitPython + subprocess fallback) |
| `plugin.py` | Hermes plugin: skill discovery, CLI bridge |

Bundled skills: `hermes_collective/skills/<skill-name>/SKILL.md`.
Template repos: `templates/repo-structure/`.
Tests: `tests/test_<module>.py`, mirroring module names.

## Architecture Philosophy

**Tool functions, not intelligence.** `aggregator.py` is a library of mechanical
operations (scan, read, write, commit). All intelligent decisions — semantic
dedup, quality scoring, conflict resolution — are made by Hermes skills using
`delegate_task` subagents. The `manager-cycle` skill (v2) orchestrates subagents;
the CLI `--legacy` flag provides a regex-based fallback.

## Build, Test, and Development Commands

- `pip install -e .`: install the package in editable mode.
- `pip install -e ".[dev]"`: install with pytest, pytest-cov, ruff.
- `hermes-collective --help`: verify CLI entry point.
- `pytest`: run the full test suite (87 tests).
- `ruff check .`: lint; `ruff check --fix .`: auto-fix.
- `hermes-collective init --name test --repo /tmp/test`: quick smoke test.

## Coding Style & Naming Conventions

Python 3.10+, Ruff line-length 100. `snake_case` for modules, functions, variables.
CLI options use Click decorators. Tool functions return dicts with "action" key
for subagent-friendly structured output. Type hints on public functions.

## Testing Guidelines

Use `pytest` with temporary directories (conftest.py fixtures: `temp_repo`,
`temp_repo_with_employee`, `temp_dir`). Test the tool function API, not internal
implementation. For CLI tests, use `click.testing.CliRunner`. File names:
`test_<module>.py`, test methods: `test_<behavior>()`.

## Commit & Pull Request Guidelines

Imperative commit style. PRs include: summary, `pytest` results, `ruff check .`
results. For CLI changes, include terminal output in description.

## Security & Configuration Tips

Do not commit tokens, personal Hermes profiles, or generated inbox content.
Treat collective repositories as shared state. Test destructive operations
with `--dry-run` first.
