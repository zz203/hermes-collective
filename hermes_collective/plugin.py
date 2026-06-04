"""
Hermes plugin entry point for hermes-collective.

Registers the collective skills and CLI as a Hermes plugin.
When installed via `hermes plugins install`, Hermes discovers
this plugin and makes the collective skills available.

The plugin hooks into:
- Skill discovery: adds collective skills to the skill registry
- CLI: registers `hermes collective` subcommand (when loaded)
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Plugin metadata — read by Hermes's plugin discovery
PLUGIN_NAME = "collective"
PLUGIN_VERSION = "0.1.0"
PLUGIN_DESCRIPTION = "Multi-agent collective learning system"


class CollectivePlugin:
    """
    Hermes plugin for the agent collective system.

    Provides:
    - 3 skills: employee-daily, manager-cycle, quality-pruning
    - CLI subcommand: hermes collective
    """

    name = PLUGIN_NAME
    version = PLUGIN_VERSION
    description = PLUGIN_DESCRIPTION

    @staticmethod
    def get_skills() -> list[tuple[str, Path]]:
        """
        Return skill name → SKILL.md path pairs for skill discovery.

        Called by Hermes's skill loader when the plugin is active.
        """
        skills_dir = Path(__file__).parent / "skills"
        skills: list[tuple[str, Path]] = []

        for skill_dir in skills_dir.iterdir():
            if not skill_dir.is_dir():
                continue
            skill_file = skill_dir / "SKILL.md"
            if skill_file.exists():
                # Skill name: collective/employee-daily, collective/manager-cycle, etc.
                skill_name = f"collective/{skill_dir.name}"
                skills.append((skill_name, skill_file))

        return skills

    @staticmethod
    def get_cli_commands() -> dict:
        """
        Return CLI command registrations.

        Hermes can optionally integrate these as `hermes collective ...`
        subcommands if the plugin CLI bridge is configured.
        """
        return {
            "collective": {
                "module": "hermes_collective.cli",
                "help": "Manage the agent collective",
            }
        }

    @staticmethod
    def on_load():
        """Called when the plugin is loaded by Hermes."""
        logger.info("Hermes Collective plugin v%s loaded", PLUGIN_VERSION)

    @staticmethod
    def on_unload():
        """Called when the plugin is unloaded."""
        logger.info("Hermes Collective plugin unloaded")


# Module-level discovery for Hermes
def discover():
    """Entry point for Hermes plugin discovery."""
    plugin = CollectivePlugin()
    return {
        "name": plugin.name,
        "version": plugin.version,
        "skills": plugin.get_skills(),
        "cli": plugin.get_cli_commands(),
    }
