"""Problem parameters: Params and VehicleType dataclasses."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VehicleType:
    """One vehicle class. count=None means unlimited availability."""
    name: str
    capacity_ft3: float
    unload_rate_min_per_ft3: float
    count: int | None = None


@dataclass(frozen=True)
class Params:
    """Global parameters (units: miles, minutes, ft3, minutes after midnight)."""
    depot_index: int
    speed_mph: float
    min_unload_min: float
    max_drive_min: float          # per route, both depot legs included
    max_duty_min: float           # per route: driving + unload
    window_open_min: float        # earliest delivery start
    window_close_min: float       # latest delivery completion
    dock_open_min: float          # first wave departure
    dock_bays: int                # vehicles departing per wave
    dock_load_min: float          # bay time to load one vehicle
    vehicle_types: tuple[VehicleType, ...]
    min_vehicles: int = 4         # at least this many routes
    # Van-only phase: 10 orders are flagged Straight-Truck-only in the CSV.
    # False = ignore the flag (vans serve everything); True = enforce it.
    enforce_eligibility: bool = False
