"""Find a feasible / cheap ORDER for a given stop SET."""
from __future__ import annotations

from .data import Instance
from .params import VehicleType


def sequence(inst: Instance, vehicle: VehicleType, stops: set[str]) -> list[str] | None:
    """Return a feasible low-cost order for `stops`, or None if none found."""
    raise NotImplementedError
