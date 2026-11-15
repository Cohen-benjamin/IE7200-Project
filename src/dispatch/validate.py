"""Independent plan validator (must not import route.py).

Why this validator exists
-------------------------
- The brief (sections 6 and 8) grades an automated pytest that re-checks
  every route of the final plan; a plan that fails cannot get full credit.
- It is a SECOND, independent implementation: it never imports route.py and
  never calls VehicleType.unload_time_min, so one bug would have to be made
  twice to slip through.
- It also checks what the workbook does not: every Monday order delivered
  exactly once, and the plan's reported numbers are true.

Plan CSV format (rows in visit order)
-------------------------------------
    route_id, vehicle, LocationIndex, OrderIndex,
    miles_total, miles_interstop, drive_min, unload_min, duty_min,
    span_min, volume_ft3            <- REPORTED metrics, same on every row
Each route's first and last row is the depot with OrderIndex empty.
Consecutive rows at the same location are one stop. Example, depot -> 4 -> 7:
    (0, -) (4, 4) (4, 10) (7, 3) (7, 41) (0, -)

Units: miles, minutes, ft3.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from dispatch.data import Instance
from dispatch.params import Params

# The numbers a plan claims for each route (names in the plan file).
METRIC_COLS = ["miles_total", "miles_interstop", "drive_min", "unload_min",
               "duty_min", "span_min", "volume_ft3"]
# Every column the plan file must have, or we cannot check it.
REQUIRED_COLS = ["route_id", "vehicle", "LocationIndex", "OrderIndex", *METRIC_COLS]


# frozen=True: a Violation can't be edited after it is created.
@dataclass(frozen=True)
class Violation:
    """One problem: which route (None = whole plan), a short code, the numbers."""

    route_id: int | None   # which route is wrong; None = the whole plan
    check: str             # short label, e.g. "span" or "duplicate_order"
    detail: str            # sentence with the numbers, for a human to read


def validate_plan(plan: pd.DataFrame, instance: Instance, params: Params,
                  metric_tol: float = 1e-6) -> list[Violation]:
    """Check a plan against raw data and return EVERY problem found.

    Inputs:
        plan: plan table in the format above (e.g. pd.read_csv of a plan file).
        instance: loaded instance (distance matrix, orders table).
        params: limits to enforce; instance.params is NOT used.
        metric_tol: allowed |reported - recomputed| per metric (float noise).
    Output:
        list of Violation; empty list = valid plan. `plan` is not modified.
    """
    # Step 0: a missing column makes every later check meaningless, so stop here.
    missing = [c for c in REQUIRED_COLS if c not in plan.columns]
    if missing:
        return [Violation(None, "schema", f"missing columns: {missing}")]
    df = plan.copy()                  # work on a copy: never change the caller's table
    # Depot rows have an empty OrderIndex; to_numeric turns empty into NaN ("no number").
    df["OrderIndex"] = pd.to_numeric(df["OrderIndex"], errors="coerce")

    # Step 1: look at the whole plan: is every order delivered exactly once?
    out = _check_coverage(df, instance)
    # Step 2: look at each route on its own. groupby splits the table by route_id;
    # the rows inside each route stay in file order (= visit order).
    for route_id, rows in df.groupby("route_id", sort=True):
        # Is it a real route? Also collects the stops/orders/vehicle for the next step.
        problems, stops, orders, vehicle, broken = _check_shape(int(route_id), rows, instance, params)
        out += problems               # add this route's shape problems to the list
        # Step 3: the numbers only make sense for a sound route, so skip them otherwise.
        if not problems and not broken:
            out += _check_numbers(int(route_id), rows, stops, orders, vehicle,
                                  instance, params, metric_tol)
    return out                        # empty list = nothing wrong


def _check_coverage(df: pd.DataFrame, instance: Instance) -> list[Violation]:
    """Unknown, duplicated and missing orders over the whole plan.

    Inputs: plan table (OrderIndex numeric, NaN on depot rows); instance.
    Output: plan-level Violations (route_id None).
    """
    # Every order number in the plan; dropna removes depot rows (they have no order).
    delivered = df["OrderIndex"].dropna().astype(int)
    known = set(instance.orders.index)    # the 43 orders that MUST be delivered
    out = []
    # Set difference (A - B = items in A that are not in B).
    # In the plan but not in the data: the plan invented an order.
    for o in sorted(set(delivered) - known):
        out.append(Violation(None, "unknown_order", f"order {o}"))
    # value_counts = how many times each order appears in the plan.
    counts = delivered.value_counts()
    # Appearing twice means it was delivered twice (same route or two routes).
    for o in sorted(counts.index[counts > 1]):
        out.append(Violation(None, "duplicate_order", f"order {o} delivered {counts[o]} times"))
    # In the data but not in the plan: an order was forgotten.
    never = sorted(known - set(delivered))
    if never:
        out.append(Violation(None, "missing_order", f"orders never delivered: {never}"))
    return out


def _check_shape(route_id: int, rows: pd.DataFrame, instance: Instance, params: Params):
    """Is this a real route? Depot at both ends, real orders at their own stops.

    Inputs: route id; this route's rows in visit order; instance; params.
    Output: (violations, stops, orders, vehicle, broken)
        stops   LocationIndex of each stop, in visit order
        orders  OrderIndex values delivered
        vehicle the VehicleType named on the route (None if unknown)
        broken  True if an unknown order (reported by coverage) blocks the numbers
    """
    depot = instance.depot_index                         # matrix index of the depot (0)
    true_loc = instance.orders["LocationIndex"]          # raw data: where each order really goes
    locs = rows["LocationIndex"].astype(int).tolist()    # location of each row, in order
    ords = rows["OrderIndex"].tolist()                   # order of each row (NaN = no order)
    # Lists we fill as we read the route, plus a flag for "can't continue".
    out, stops, orders, broken = [], [], [], False

    # --- Both ends of a route must be the depot, delivering nothing ---------
    starts_ok = locs[0] == depot and pd.isna(ords[0])    # first row = depot, no order
    # (needs 2+ rows, or one row would count as both start and end)
    ends_ok = len(rows) >= 2 and locs[-1] == depot and pd.isna(ords[-1])
    if not starts_ok:
        out.append(Violation(route_id, "depot_start", f"first row is location {locs[0]}"))
    if not ends_ok:
        out.append(Violation(route_id, "depot_end", f"last row is location {locs[-1]}"))

    # --- Which rows are real stops? Everything between the depot rows -------
    # If an end row is missing, that row is a real stop: keep it, don't skip it.
    first = 1 if starts_ok else 0                        # skip row 0 only if it is the depot
    last = len(locs) - 1 if ends_ok else len(locs)       # skip the last row only if it is the depot
    # zip walks the two lists together: (location, order) one row at a time.
    for loc, o in zip(locs[first:last], ords[first:last]):
        if pd.isna(o):                                   # a stop row with no order,
            out.append(Violation(route_id, "order_location",    # e.g. depot mid-route
                                 f"row at location {loc} has no order"))
            continue                                     # nothing else to check on this row
        o = int(o)                                       # NaN made it a float; back to a whole number
        if o not in true_loc.index:                      # order doesn't exist in the data:
            broken = True                                # coverage already reported it, so
            continue                                     # just skip the numbers for this route
        # An order must be delivered at its own location, from the raw data.
        # This one rule also catches a bogus location or a depot visit mid-route.
        if int(true_loc[o]) != loc:
            out.append(Violation(route_id, "order_location",
                                 f"order {o} belongs at {int(true_loc[o])}, row says {loc}"))
        orders.append(o)                                 # remember the order for the numbers
        # Same location as the previous row = same stop (two orders there).
        # A different location = a new stop.
        if not stops or stops[-1] != loc:
            if loc in stops:                             # new stop, but visited before: a revisit
                out.append(Violation(route_id, "repeat_stop", f"location {loc} visited twice"))
            stops.append(loc)
    # A route must deliver something (unless an unknown order already explains it).
    if not orders and not broken:
        out.append(Violation(route_id, "empty_route", "route delivers no orders"))

    # --- The vehicle name must match one in params --------------------------
    name = rows["vehicle"].iloc[0]                       # the route's vehicle, e.g. "Van"
    # next(...) takes the first match, or None if there is none.
    vehicle = next((vt for vt in params.vehicle_types if vt.name == name), None)
    if vehicle is None:
        out.append(Violation(route_id, "unknown_vehicle", f"vehicle {name!r}"))
    return out, stops, orders, vehicle, broken


def _check_numbers(route_id, rows, stops, orders, vehicle, instance, params, metric_tol):
    """Recompute the route from raw data; check the 4 limits and reported metrics.

    Inputs: route id, its rows, stops and orders (from _check_shape), vehicle,
        instance, params, metric_tol.
    Output: Violations for limits exceeded ("volume", "drive", "duty", "span")
        and for reported numbers that differ ("metric_mismatch").
    """
    # --- Rebuild every number from raw data (never trust the plan's claims) -
    d = instance.dist_mi                                 # raw distance matrix (miles)
    # The full drive: depot -> each stop in order -> depot.
    path = [instance.depot_index, *stops, instance.depot_index]
    # zip(path, path[1:]) pairs each location with the next one = every leg.
    miles = sum(d[a, b] for a, b in zip(path, path[1:]))
    # Same, but only between stops: no depot legs (this feeds SPAN).
    inter = sum(d[a, b] for a, b in zip(stops, stops[1:]))
    vols = instance.orders.loc[orders, "Volume_ft3"]     # raw volume of each order on this route
    # Unload is paid PER ORDER: apply the 30-min floor to each, then add them up.
    unload = sum(max(vehicle.min_unload_min, vehicle.unload_min_per_ft3 * v) for v in vols)
    rate = params.drive_min_per_mile                     # minutes of driving per mile
    calc = {                                             # what the route really costs
        "miles_total": float(miles),
        "miles_interstop": float(inter),
        "drive_min": float(miles) * rate,                # all driving, depot legs included
        "unload_min": float(unload),
        "duty_min": float(miles) * rate + float(unload), # driving + unloading
        "span_min": float(inter) * rate + float(unload), # no depot legs: the delivery window
        "volume_ft3": float(vols.sum()),
    }
    out = []

    # --- The four limits (label, number to test, its limit) ------------------
    limits = [("volume", "volume_ft3", vehicle.capacity_ft3),
              ("drive", "drive_min", params.max_drive_min),
              ("duty", "duty_min", params.max_duty_min),
              # span limit = length of the delivery window (e.g. 1080 - 480 = 600)
              ("span", "span_min", params.window_end_min - params.window_start_min)]
    for code, key, limit in limits:
        if calc[key] > limit:                            # over the limit by any amount = violation
            out.append(Violation(route_id, code,
                                 f"{key} {calc[key]:.2f} > {limit:.2f} (over by {calc[key] - limit:.2f})"))

    # --- Do the plan's claimed numbers match the real ones? ------------------
    claimed = rows.iloc[0]                               # claims repeat on every row; read the first
    for key, value in calc.items():
        reported = claimed[key]
        # Missing, or off by more than float rounding noise (metric_tol) = a wrong claim.
        if pd.isna(reported) or abs(float(reported) - value) > metric_tol:
            out.append(Violation(route_id, "metric_mismatch",
                                 f"{key}: reported {reported}, recomputed {value:.6f}"))
    return out
