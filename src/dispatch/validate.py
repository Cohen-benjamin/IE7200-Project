"""Independent plan validator.

Recomputes everything from the raw Instance; intentionally does NOT import
route.py so solver bugs can't hide behind shared code.
"""
from __future__ import annotations

from .data import Instance
from .solution import Solution


def validate(inst: Instance, sol: Solution) -> list[str]:
    """Return a list of violations (empty = valid plan).

    Checks: every stop served exactly once, capacity, time windows,
    fleet counts, route duration limits, depot start/end.
    """
    raise NotImplementedError
