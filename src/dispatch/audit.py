"""Data property checks (run before solving; findings go in DATA_FINDINGS.md)."""
from __future__ import annotations

from .data import Instance


def audit(inst: Instance) -> list[str]:
    """Return a list of human-readable issues found in the instance.

    Planned checks: missing/duplicate IDs, negative demand, demand > max capacity,
    infeasible time windows, asymmetric/triangle-violating distances, unreachable stops.
    """
    issues: list[str] = []
    raise NotImplementedError
