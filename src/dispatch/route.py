"""Route metrics and feasibility for a given stop SEQUENCE."""
from __future__ import annotations

from dataclasses import dataclass

from .data import Instance
from .params import VehicleType


@dataclass
class RouteMetrics:
    distance: float
    duration: float
    load: float
    cost: float
    feasible: bool
    violations: list[str]


def evaluate(inst: Instance, vehicle: VehicleType, seq: list[str]) -> RouteMetrics:
    """Evaluate depot -> seq -> depot. Does not reorder stops."""
    raise NotImplementedError
