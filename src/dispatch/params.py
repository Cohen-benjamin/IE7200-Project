"""Problem parameters: Params and VehicleType dataclasses."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class VehicleType:
    """One vehicle class in the fleet."""
    name: str
    capacity: float          # load units
    count: int               # vehicles available
    fixed_cost: float = 0.0  # per vehicle used
    cost_per_km: float = 0.0
    max_route_time: float | None = None  # minutes; None = unlimited


@dataclass(frozen=True)
class Params:
    """Global run parameters."""
    depot_id: str
    vehicle_types: tuple[VehicleType, ...] = field(default_factory=tuple)
    service_time_default: float = 0.0  # minutes per stop
    speed_kmh: float = 50.0
    seed: int = 0
