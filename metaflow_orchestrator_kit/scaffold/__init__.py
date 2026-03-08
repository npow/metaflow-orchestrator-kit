"""
Scaffold tool for Metaflow orchestrator extensions.

Usage:
    python -m metaflow_orchestrator_kit.scaffold my_scheduler

or via the installed entry point:
    metaflow-orchestrator-scaffold my_scheduler
"""

from .__main__ import scaffold, main

__all__ = ["scaffold", "main"]
