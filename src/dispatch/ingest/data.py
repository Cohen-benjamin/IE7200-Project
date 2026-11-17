"""Ingestion: data/csv/*.csv -> Instance object.

Units: distances in miles, volumes in ft3, times in minutes.
Only shape/integrity is checked here; route feasibility lives in route.py
and validate.py.
"""
# Allows modern type hints (``dict[int, tuple[int, ...]]``) on older Pythons.
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# numpy: fast numeric arrays (the distance matrix).
import numpy as np
# pandas: labelled tables (orders, locations).
import pandas as pd

# Reuse the parameter loader so there is one place that reads parameters.csv.
from dispatch.params import Params, load_params

# Filename prefix of the Monday instance; files are named <prefix>_<table>.csv.
# One named constant so the string is not scattered through the code.
FILE_PREFIX = "ie7200_Mon"


# frozen=True: fields can't be reassigned after creation (shallow protection:
# the contents of a field such as the DataFrame could still be edited).
@dataclass(frozen=True)
class Instance:
    """One problem instance.

    Attributes:
        params: limits and fleet (see params.Params).
        dist_mi: (L, L) distance matrix, miles. Symmetric, NOT metric.
            Row/column ``depot_index`` is the depot. Read-only.
        depot_index: row/column of the depot in ``dist_mi``.
        orders: one row per order, indexed by OrderIndex. Columns:
            GlobalOrderId, LocationIndex, GlobalLocationId, Volume_ft3,
            UnloadTime_min, RequiresStraightTruck, AllowedVehicles.
        locations: one row per location, indexed by LocationIndex. Columns:
            GlobalLocationId, IsDepot, DistanceFromDepot_mi, OrderCount,
            TotalVolume_ft3.
        orders_at: LocationIndex -> tuple of OrderIndex delivered there
            (depot excluded). Tuples so shared data cannot be mutated.Creates a way
            to see which orders get delivered at each stop that is covered.
    """

    params: Params
    dist_mi: np.ndarray               # dist_mi[i, j] = miles from location i to j
    depot_index: int
    orders: pd.DataFrame              # row label = OrderIndex (0..42)
    locations: pd.DataFrame           # row label = LocationIndex (0..34)
    orders_at: dict[int, tuple[int, ...]]   # stop -> its orders

    @property
    def n_orders(self) -> int:
        """Number of orders (unit of coverage)."""
        # One row per order, so row count = order count (43).
        return len(self.orders)

    @property
    def stops(self) -> tuple[int, ...]:
        """Sorted LocationIndex of every delivery stop (depot excluded)."""
        # The keys of orders_at are exactly the locations that have orders
        # (the depot has none, so it is absent). sorted() gives a stable order.
        return tuple(sorted(self.orders_at))


def load_instance(data_dir: Path) -> Instance:
    """Load the Monday instance from CSV files.

    Inputs:
        data_dir: folder holding ``<FILE_PREFIX>_{distance,locations,orders,
            parameters,vehicle_types}.csv`` (e.g. ``data/csv``).
    Output:
        Instance (miles, ft3, minutes). Raises ValueError if shapes or
        order/location references are inconsistent.
    """
    # Accept a str or a Path from the caller; Path() makes both behave the same.
    data_dir = Path(data_dir)

    def path(table: str) -> Path:
        """Path of one CSV table for this instance."""
        # e.g. table="orders" -> data/csv/ie7200_Mon_orders.csv
        return data_dir / f"{FILE_PREFIX}_{table}.csv"

    # --- Parameters ---------------------------------------------------------
    # Params (limits + Van) for the model.
    params = load_params(path("parameters"))
    # Re-read the same file only to get three counts that are data facts, not
    # model limits: N (orders), L (matrix size), DepotIndex. Used for checks.
    raw = pd.read_csv(path("parameters")).set_index("Parameter")["Value"]
    n_orders_expected = int(raw["N"])          # should be 43 for this data set
    n_locations_expected = int(raw["L"])       # should be 35 (depot included) for this data set
    depot_index = int(raw["DepotIndex"])       # should be 0

    # --- Distance matrix ----------------------------------------------------
    # The first CSV column ("FromLocationIndex") is a row label, not a distance,
    # so .iloc[:, 1:] drops it. to_numpy(float) gives a plain 2-D float array.
    dist = pd.read_csv(path("distance")).iloc[:, 1:].to_numpy(dtype=float)
    # Integrity check: must be L x L, or something is wrong with the file.
    if dist.shape != (n_locations_expected, n_locations_expected):
        raise ValueError(
            f"distance matrix is {dist.shape}, expected "
            f"{(n_locations_expected, n_locations_expected)}"
        )
    # Make the array read-only so a solver can't accidentally edit a distance.
    dist.flags.writeable = False

    # --- Orders -------------------------------------------------------------
    # orders.csv has volume + unload time; index by OrderIndex so orders.loc[o]
    # means "order o".
    orders = pd.read_csv(path("orders")).set_index("OrderIndex")
    # vehicle_types.csv holds per-order eligibility, same OrderIndex labels.
    eligibility = pd.read_csv(path("vehicle_types")).set_index("OrderIndex")
    # Attach the two eligibility columns to each order, matching rows by label.
    # how="left" keeps every order even if eligibility were missing (we check next).
    orders = orders.join(
        eligibility[["RequiresStraightTruck", "AllowedVehicles"]], how="left"
    )
    # Integrity: the number of orders must match N in parameters.csv.
    if len(orders) != n_orders_expected:
        raise ValueError(f"{len(orders)} orders, expected {n_orders_expected}")
    # A left join leaves NaN where there was no match -> an order lacks a row.
    if orders["RequiresStraightTruck"].isna().any():
        raise ValueError("some orders have no row in vehicle_types.csv")

    # --- Locations ----------------------------------------------------------
    locations = pd.read_csv(path("locations")).set_index("LocationIndex")
    # Set difference: location ids used by orders but absent from locations.csv.
    # used to make sure all location listed in orders are in locations list
    missing = set(orders["LocationIndex"]) - set(locations.index)
    if missing:
        raise ValueError(f"orders reference unknown locations: {sorted(missing)}")

    # --- orders_at: stop -> orders delivered there ---------------------------
    # groupby splits the orders table by LocationIndex; for each group, grp.index
    # holds that group's OrderIndex labels (not row positions). int() converts
    # numpy integers to plain Python ints; tuple() freezes the list.
    orders_at = {
        int(loc): tuple(int(o) for o in grp.index)
        for loc, grp in orders.groupby("LocationIndex")
    }

    # Bundle everything into the frozen Instance and hand it back.
    return Instance(
        params=params,
        dist_mi=dist,
        depot_index=depot_index,
        orders=orders,
        locations=locations,
        orders_at=orders_at,
    )
