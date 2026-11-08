"""Ingestion: data/csv/*.csv -> Instance object."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from .params import Params, VehicleType

PREFIX = "ie7200_Mon"


@dataclass(frozen=True)
class Order:
    index: int
    global_id: int
    location: int            # row/col in the distance matrix
    volume_ft3: float
    unload_min: float        # as given in orders CSV (30-min floor already applied)
    requires_straight_truck: bool


@dataclass(frozen=True)
class Instance:
    params: Params
    orders: tuple[Order, ...]
    dist: tuple[tuple[float, ...], ...]   # miles, dist[i][j]

    @property
    def depot(self) -> int:
        return self.params.depot_index

    def travel_min(self, i: int, j: int) -> float:
        """Travel time in minutes at constant speed."""
        return self.dist[i][j] / self.params.speed_mph * 60.0

    def orders_at(self, location: int) -> tuple[Order, ...]:
        return tuple(o for o in self.orders if o.location == location)

    @property
    def total_volume_ft3(self) -> float:
        return sum(o.volume_ft3 for o in self.orders)


def _rows(path: Path) -> list[dict]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def load_csv_dir(path: str | Path, day: str = "Mon") -> Instance:
    """Load an instance from `path` (e.g. data/csv). Van-only fleet, unlimited count."""
    d = Path(path)
    pre = f"ie7200_{day}"

    raw = {r["Parameter"]: r["Value"] for r in _rows(d / f"{pre}_parameters.csv")}
    p = {k: float(v) for k, v in raw.items() if k != "Day"}

    with (d / f"{pre}_distance.csv").open(newline="") as f:
        rd = csv.reader(f)
        next(rd)  # header row of column indices
        dist = tuple(tuple(float(x) for x in row[1:]) for row in rd)

    elig = {int(r["OrderIndex"]): r["RequiresStraightTruck"] == "1"
            for r in _rows(d / f"{pre}_vehicle_types.csv")}
    orders = tuple(
        Order(
            index=int(r["OrderIndex"]),
            global_id=int(r["GlobalOrderId"]),
            location=int(r["LocationIndex"]),
            volume_ft3=float(r["Volume_ft3"]),
            unload_min=float(r["UnloadTime_min"]),
            requires_straight_truck=elig[int(r["OrderIndex"])],
        )
        for r in _rows(d / f"{pre}_orders.csv")
    )

    params = Params(
        depot_index=int(p["DepotIndex"]),
        speed_mph=p["SpeedMPH"],
        min_unload_min=p["MinUnloadTimeMin"],
        max_drive_min=p["MaxDriveTimeMin"],
        max_duty_min=p["MaxDutyTimeMin"],
        window_open_min=p["DeliveryWindowOpenMin"],
        window_close_min=p["DeliveryWindowCloseMin"],
        dock_open_min=p["DockOpenMin"],
        dock_bays=int(p["DockBays"]),
        dock_load_min=p["DockLoadMinPerVehicle"],
        vehicle_types=(VehicleType("Van", p["VehicleCapacity"], p["UnloadRateMinPerFt3"]),),
    )

    n, l = int(p["N"]), int(p["L"])
    if len(orders) != n:
        raise ValueError(f"expected {n} orders, found {len(orders)}")
    if len(dist) != l or any(len(r) != l for r in dist):
        raise ValueError(f"distance matrix is not {l}x{l}")
    return Instance(params=params, orders=orders, dist=dist)
