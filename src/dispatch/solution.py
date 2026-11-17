"""Solution object, reporting, and export.

A Solution is one complete Monday plan: every route a solver built, plus how
it was made (method name, runtime). Every solver returns one
(``solve(inst) -> Solution``). Route numbers always come from
``route.route_metrics`` - they are never typed in by hand.

The CSV written by ``Solution.to_csv`` is the plan format that
``validate.validate_plan`` reads (rows in visit order, a depot row at both
ends of each route, one row per order). This module does not import
validate.py: the validator must stay independent of the code it checks.

Units: miles, minutes, ft3; utilization in percent.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import pandas as pd

from dispatch.ingest.data import Instance
from dispatch.route import RouteMetrics, route_metrics

# The numbers each route reports (same names validate.py reads).
# Copied, not imported, so validate.py and this module stay independent.
METRIC_COLS = ["miles_total", "miles_interstop", "drive_min", "unload_min",
               "duty_min", "span_min", "volume_ft3"]
# Column order of the plan CSV file.
CSV_COLS = ["route_id", "vehicle", "LocationIndex", "OrderIndex",
            *METRIC_COLS, "method", "runtime_s"]
# The four limits: (label, metric that uses it up, its slack = room left).
LIMITS = [("volume", "volume_ft3", "slack_volume_ft3"),
          ("drive", "drive_min", "slack_drive_min"),
          ("duty", "duty_min", "slack_duty_min"),
          ("span", "span_min", "slack_span_min")]


# frozen=True: a Route can't be edited after it is created.
@dataclass(frozen=True)
class Route:
    """One van's trip.

    Attributes:
        route_id: number of the route in the plan (1, 2, ...).
        vehicle: vehicle type name, e.g. "Van".
        stops: LocationIndex values in visit order (depot not included).
        orders: OrderIndex values delivered, grouped in stop order.
        metrics: RouteMetrics from route.route_metrics (miles, minutes, ft3).
    """

    route_id: int                 # 1, 2, 3 ... within the plan
    vehicle: str                  # vehicle type name, e.g. "Van"
    stops: tuple[int, ...]        # where the van stops, in visit order
    orders: tuple[int, ...]       # what it delivers, grouped by stop
    metrics: RouteMetrics         # miles/minutes/volume + slacks, from route.py


@dataclass(frozen=True)
class Solution:
    """A full plan: all routes, plus the method and its runtime.

    Attributes:
        routes: every route in the plan.
        method: name of the solver that built it, e.g. "nn_2opt".
        runtime_s: how long the solver took (seconds).
    """

    routes: tuple[Route, ...]     # every van's trip
    method: str                   # which solver built the plan
    runtime_s: float              # how long it took, in seconds

    @property
    def n_routes(self) -> int:
        """Number of routes = number of vans dispatched."""
        return len(self.routes)                              # one route per van

    @property
    def total_miles(self) -> float:
        """Sum of every route's miles, depot legs included (mi)."""
        # The headline cost the solvers try to make small.
        return float(sum(r.metrics.miles_total for r in self.routes))

    def utilization(self) -> pd.DataFrame:
        """How full each route is on each limit, in percent.

        Output:
            DataFrame indexed by route_id, columns volume_pct, drive_pct,
            duty_pct, span_pct. Each = used / limit x 100, where
            limit = used + slack (so no limits need to be passed in).
            A zero limit gives NaN instead of a division error.
        """
        rows = []                                            # one dict per route
        for r in self.routes:
            m = r.metrics
            row = {"route_id": r.route_id}
            for label, used_name, slack_name in LIMITS:      # the 4 limits in turn
                used = getattr(m, used_name)                 # e.g. drive_min = 603
                # slack = limit - used, so used + slack gives the limit back.
                limit = used + getattr(m, slack_name)        # e.g. 603 + 57 = 660
                # Percent of the limit used; NaN if the limit is 0 (no dividing by 0).
                row[f"{label}_pct"] = used / limit * 100 if limit else float("nan")
            rows.append(row)
        # Name the columns even when there are no routes, so the table shape is fixed.
        cols = ["route_id"] + [f"{label}_pct" for label, _, _ in LIMITS]
        return pd.DataFrame(rows, columns=cols).set_index("route_id")

    def tightest_slack(self) -> pd.DataFrame:
        """For each limit, the route with the least room left.

        Output:
            DataFrame indexed by constraint (volume, drive, duty, span),
            columns slack (ft3 or min) and route_id. Empty if no routes.
        """
        rows = []
        for label, _, slack_name in LIMITS:                  # one row per limit
            if not self.routes:
                break                                        # no routes: nothing to compare
            # min(..., key=...) picks the route whose slack is smallest.
            r = min(self.routes, key=lambda r: getattr(r.metrics, slack_name))
            rows.append({"constraint": label, "slack": getattr(r.metrics, slack_name),
                         "route_id": r.route_id})
        return pd.DataFrame(rows, columns=["constraint", "slack", "route_id"]).set_index("constraint")

    def summary_table(self) -> pd.DataFrame:
        """One row per route plus a "total" row.

        Output:
            DataFrame with route, vehicle, n_stops, n_orders, stops (e.g.
            "4-7"), the 7 metrics, the 4 utilization %, and feasible.
            The total row adds up the additive columns (counts, miles,
            minutes driven/unloaded/on duty, volume); span and the
            percentages do not add up, so they are left empty there.
        """
        util = self.utilization()                            # the 4 % per route
        rows = []
        for r in self.routes:
            # Who/what/where for this route; stops shown as "4-7" for easy reading.
            row = {"route": r.route_id, "vehicle": r.vehicle,
                   "n_stops": len(r.stops), "n_orders": len(r.orders),
                   "stops": "-".join(str(s) for s in r.stops)}
            row.update({c: getattr(r.metrics, c) for c in METRIC_COLS})   # the 7 numbers
            row.update(util.loc[r.route_id].to_dict())        # the 4 percentages
            row["feasible"] = r.metrics.feasible              # passes all 4 limits?
            rows.append(row)
        table = pd.DataFrame(rows)
        # Only these columns make sense to add up across routes.
        additive = ["n_stops", "n_orders", "miles_total", "miles_interstop",
                    "drive_min", "unload_min", "duty_min", "volume_ft3"]
        total = {"route": "total", **{c: sum(row[c] for row in rows) for c in additive},
                 "feasible": all(row["feasible"] for row in rows)}   # plan feasible = all routes
        # Stack the total row under the route rows.
        return pd.concat([table, pd.DataFrame([total])], ignore_index=True)

    def to_csv(self, path: Path, instance: Instance) -> None:
        """Write the plan CSV (format in the module docstring).

        Inputs:
            path: file to write.
            instance: needed for the depot index and each order's location.
        Output:
            None. A plan with no routes writes the header row only.
        """
        depot = instance.depot_index                         # matrix index of the depot (0)
        where = instance.orders["LocationIndex"]             # each order's location
        rows = []
        for r in self.routes:
            # Columns that repeat on every row of this route.
            common = {"route_id": r.route_id, "vehicle": r.vehicle,
                      **{c: getattr(r.metrics, c) for c in METRIC_COLS},
                      "method": self.method, "runtime_s": self.runtime_s}
            # --- leave the depot (no order) ------------------------------------
            rows.append({**common, "LocationIndex": depot, "OrderIndex": None})
            # --- one row per order, stop by stop in visit order -----------------
            for stop in r.stops:
                for o in r.orders:
                    if where[o] == stop:                     # this order is delivered here
                        rows.append({**common, "LocationIndex": stop, "OrderIndex": o})
            # --- return to the depot (no order) --------------------------------
            rows.append({**common, "LocationIndex": depot, "OrderIndex": None})
        # columns=CSV_COLS fixes the column order (and gives a header if empty).
        pd.DataFrame(rows, columns=CSV_COLS).to_csv(path, index=False)


def make_solution(
    route_specs: Sequence[tuple[str, Sequence[int], Sequence[int]]],
    instance: Instance,
    method: str,
    runtime_s: float,
) -> Solution:
    """Build a Solution from plain route descriptions.

    Inputs:
        route_specs: list of (vehicle_name, stops in visit order, orders).
        instance: problem instance (metrics come from route.route_metrics,
            which also rejects invalid routes with ValueError).
        method: solver name.
        runtime_s: solver runtime (seconds).
    Output:
        Solution with route_ids 1..n. Each route's orders are put in stop
        order (orders at the same stop keep their given order), the same
        order to_csv writes them in.
    """
    where = instance.orders["LocationIndex"]                 # each order's location
    routes = []
    # enumerate(..., start=1) numbers the routes 1, 2, 3 ...
    for route_id, (vehicle, stops, orders) in enumerate(route_specs, start=1):
        stops = tuple(int(s) for s in stops)                 # plain ints, frozen as a tuple
        # position[stop] = where that stop comes in the route (0, 1, 2 ...).
        position = {s: i for i, s in enumerate(stops)}
        # Put orders in stop order, matching how to_csv writes them.
        # sorted() is stable: orders at one
        # stop keep their relative order. where.get(o) is None for an unknown
        # order; it sorts last and route_metrics then rejects it clearly.
        orders = tuple(sorted((int(o) for o in orders),
                              key=lambda o: position.get(where.get(o), len(stops))))
        # The single source of route numbers: route.py.
        m = route_metrics(stops, orders, instance, instance.params.vehicle(vehicle))
        routes.append(Route(route_id, vehicle, stops, orders, m))
    return Solution(tuple(routes), method, float(runtime_s))
