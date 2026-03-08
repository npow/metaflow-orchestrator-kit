"""
metaflow-orchestrator-kit — development kit for building Metaflow orchestrator extensions.

Exports:
    Cap              — OrchestratorCapabilities enum
    REQUIRED         — frozenset of capabilities every orchestrator must implement
    OPTIONAL         — frozenset of capabilities that may be declared unsupported
"""

from .capabilities import Cap, REQUIRED, OPTIONAL

__version__ = "0.1.0"
__all__ = ["Cap", "REQUIRED", "OPTIONAL"]
