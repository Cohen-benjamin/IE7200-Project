"""Data property checks.

Every function here REPORTS on an Instance and returns a table or list.
Nothing is printed and nothing in the Instance is modified.
Each check tests one modelling assumption (stated in its docstring).

Units: miles, minutes, ft3.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from dispatch.data import Instance
from dispatch.params import VAN_NAME

# Status labels used by one_visit_checks. Labels, not model parameters.
OK, WARN, FAIL = "OK", "WARN", "FAIL"


@dataclass(frozen=True)
class Finding:
    """One result of a "one visit per location" check.

    Attributes:
        check: short name of the check.
        status: "OK" (assumption holds), "WARN" (holds but with a caveat),
            or "FAIL" (assumption is broken by this data).
        detail: human-readable explanation, with the numbers.
    """

    check: str
    status: str
    detail: str


# --- 1. Triangle inequality --------------------------------------------------

def triangle_violations(inst: Instance) -> pd.DataFrame:
    """Every case where driving i -> k -> j is SHORTER than driving i -> j direct.

    Assumption tested: the distance matrix gives shortest paths (it is metric).
    If it is not, a direct arc overstates the true driving cost, and a route
    could save miles by passing through k without stopping there.

    Inputs:
        inst: the problem instance (uses dist_mi and params.drive_min_per_mile).
    Output:
        DataFrame, one row per (i, j, k) with i < j and i, j, k all different,
        where d[i,j] > d[i,k] + d[k,j]. Columns:
            i, j          endpoints of the direct leg (LocationIndex)
            k             the shortcut location
            direct_mi     d[i,j] (miles)
            via_k_mi      d[i,k] + d[k,j] (miles)
            excess_mi     direct_mi - via_k_mi (miles saved by the detour)
            excess_min    excess_mi converted to driving minutes
        Sorted by excess_mi, largest first. Includes the depot as i, j or k.
        Because the matrix is symmetric, (j, i, k) is the same case and is
        not listed twice (that is why i < j).
    """
    d = inst.dist_mi
    # via[i, k, j] = d[i, k] + d[k, j]: every two-leg trip, built by broadcasting.
    #   d[:, :, None] has shape (n, n, 1) -> d[i, k] repeated along j
    #   d[None, :, :] has shape (1, n, n) -> d[k, j] repeated along i
    via = d[:, :, None] + d[None, :, :]
    # direct[i, 0, j] = d[i, j], shaped (n, 1, n) so it lines up with via[i, k, j].
    direct = d[:, None, :]
    # Positive excess = direct leg is longer than going through k = a violation.
    # Distances are whole miles, so strict ">" needs no tolerance.
    i, k, j = np.nonzero(direct > via)
    # Keep each unordered pair once (i < j). k equal to i or j can never be a
    # violation (d[i,i] = 0, so the "detour" equals the direct leg), but we
    # filter explicitly so the rule "three different locations" is visible.
    keep = (i < j) & (k != i) & (k != j)
    i, j, k = i[keep], j[keep], k[keep]

    table = pd.DataFrame({
        "i": i,
        "j": j,
        "k": k,
        "direct_mi": d[i, j],
        "via_k_mi": d[i, k] + d[k, j],
    })
    table["excess_mi"] = table["direct_mi"] - table["via_k_mi"]
    # Convert miles to minutes with the same rate the routes will use.
    table["excess_min"] = table["excess_mi"] * inst.params.drive_min_per_mile
    # Largest excess first; ties broken by location numbers for a stable order.
    return table.sort_values(
        ["excess_mi", "i", "j", "k"], ascending=[False, True, True, True]
    ).reset_index(drop=True)


def violation_location_counts(violations: pd.DataFrame) -> pd.DataFrame:
    """How often each location takes part in a triangle violation.

    Assumption tested: violations are scattered noise, not concentrated on a
    few locations (concentration hints at one bad distance row/column).

    Inputs:
        violations: output of triangle_violations.
    Output:
        DataFrame indexed by LocationIndex (only locations that appear), columns:
            as_endpoint   times the location is i or j (its direct leg is "too long")
            as_shortcut   times the location is k (it is the useful detour point)
            total         as_endpoint + as_shortcut
        Sorted by total, largest first.
    """
    # Stack the i and j columns into one series and count each location.
    endpoint = pd.concat([violations["i"], violations["j"]]).value_counts()
    shortcut = violations["k"].value_counts()
    # Align both counts on location number; locations missing from one get 0.
    counts = pd.DataFrame({"as_endpoint": endpoint, "as_shortcut": shortcut})
    counts = counts.fillna(0).astype(int)
    counts["total"] = counts["as_endpoint"] + counts["as_shortcut"]
    counts.index.name = "LocationIndex"
    return counts.sort_values(["total"], ascending=False, kind="stable")


# --- 2. Per-location profile -------------------------------------------------

def location_profile(inst: Instance, vehicle_name: str = VAN_NAME) -> pd.DataFrame:
    """Resource use of each stop on its own, compared to each limit.

    Assumption tested: every location "fits" in one vehicle on each resource
    separately (distance, volume, unload time).

    Inputs:
        inst: the problem instance.
        vehicle_name: which VehicleType to measure against (M1: "Van").
    Output:
        DataFrame indexed by LocationIndex (stops only, depot excluded). Columns:
            dist_from_depot_mi    d[depot, s] (miles)
            round_trip_drive_min  (d[depot, s] + d[s, depot]) * min/mi (minutes)
            drive_slack_min       max_drive_min - round_trip_drive_min
            n_orders              orders delivered at this stop
            total_volume_ft3      sum of those orders' volumes (ft3)
            volume_slack_ft3      vehicle capacity - total_volume_ft3
            total_unload_min      sum of per-order unload times (minutes)
            unload_slack_min      max_span_min - total_unload_min
        A negative slack means the limit is exceeded.
    """
    p = inst.params
    vehicle = p.vehicle(vehicle_name)
    d = inst.dist_mi
    depot = inst.depot_index

    rows = []
    for s in inst.stops:
        # Order indices delivered at this stop, then their volumes.
        order_ids = list(inst.orders_at[s])
        volumes = inst.orders.loc[order_ids, "Volume_ft3"]
        # Out and back. Written as two legs (not 2 * d) so it stays correct
        # even if the matrix were ever asymmetric.
        round_trip_mi = d[depot, s] + d[s, depot]
        round_trip_min = round_trip_mi * p.drive_min_per_mile
        # Unload is paid PER ORDER (floor applies to each), then summed.
        unload_min = sum(vehicle.unload_time_min(v) for v in volumes)
        rows.append({
            "LocationIndex": s,
            "dist_from_depot_mi": d[depot, s],
            "round_trip_drive_min": round_trip_min,
            "drive_slack_min": p.max_drive_min - round_trip_min,
            "n_orders": len(order_ids),
            "total_volume_ft3": volumes.sum(),
            "volume_slack_ft3": vehicle.capacity_ft3 - volumes.sum(),
            "total_unload_min": unload_min,
            "unload_slack_min": p.max_span_min - unload_min,
        })
    return pd.DataFrame(rows).set_index("LocationIndex")


# --- 3. Single-stop feasibility ---------------------------------------------

def single_stop_feasibility(inst: Instance, vehicle_name: str = VAN_NAME) -> pd.DataFrame:
    """Can each stop be served by one vehicle on a route depot -> s -> depot?

    Assumption tested: the problem is feasible at all. If some stop fails
    alone, no route containing it can pass, and its orders can never be
    covered by a one-visit model.

    Inputs:
        inst: the problem instance.
        vehicle_name: which VehicleType to test (M1: "Van").
    Output:
        DataFrame indexed by LocationIndex. Slack on all four constraints
        (limit minus usage; negative = violated):
            volume_slack_ft3  capacity - volume
            drive_slack_min   max_drive_min - round-trip drive
            duty_slack_min    max_duty_min - (round-trip drive + unload)
            span_slack_min    max_span_min - (inter-stop drive + unload);
                              a single stop has NO inter-stop leg, so span = unload
        plus:
            feasible          True if every slack >= 0
            binding           the constraint with the least slack relative to
                              its limit (the one that will bite first)
    """
    p = inst.params
    vehicle = p.vehicle(vehicle_name)
    prof = location_profile(inst, vehicle_name)

    duty_min = prof["round_trip_drive_min"] + prof["total_unload_min"]
    table = pd.DataFrame({
        "volume_slack_ft3": prof["volume_slack_ft3"],
        "drive_slack_min": prof["drive_slack_min"],
        "duty_slack_min": p.max_duty_min - duty_min,
        # Inter-stop drive is 0 for a one-stop route, so span usage = unload.
        "span_slack_min": p.max_span_min - prof["total_unload_min"],
    })
    # Slack divided by its own limit, so minutes and ft3 can be compared:
    # 0.09 means "9% of the limit is left".
    limits = {
        "volume_slack_ft3": vehicle.capacity_ft3,
        "drive_slack_min": p.max_drive_min,
        "duty_slack_min": p.max_duty_min,
        "span_slack_min": p.max_span_min,
    }
    relative = pd.DataFrame({col: table[col] / lim for col, lim in limits.items()})
    table["feasible"] = (table[list(limits)] >= 0).all(axis=1)
    # idxmin(axis=1) gives, per row, the column name with the smallest value.
    table["binding"] = relative.idxmin(axis=1)
    return table


# --- 4. "One visit per location" validity ------------------------------------

def one_visit_checks(
    inst: Instance, violations: pd.DataFrame, vehicle_name: str = VAN_NAME
) -> list[Finding]:
    """Checks that a "visit each location once, deliver all its orders,
    drive direct arcs" model is valid for this data.

    Inputs:
        inst: the problem instance.
        violations: output of triangle_violations(inst).
        vehicle_name: vehicle type to test against (M1: "Van").
    Output:
        list of Finding, one per check (a) to (f), in that order:
          a. stop volume > capacity          -> FAIL: must split the stop across vans
          b. stop infeasible alone           -> FAIL: same, for time limits
          c. duplicate locations             -> WARN: same place counted as two stops
          d. stops usable as shortcuts       -> WARN: passing through a stop again
                                                could beat the direct arc
          e. depot legs not shortest         -> WARN: DistanceFromDepot overstates
          f. mixed vehicle eligibility       -> WARN (M2 only): one vehicle type
                                                cannot serve all orders at the stop
    """
    findings: list[Finding] = []
    feas = single_stop_feasibility(inst, vehicle_name)
    d = inst.dist_mi
    depot = inst.depot_index

    # (a) A stop whose orders exceed one vehicle would need two visits.
    over = feas.index[feas["volume_slack_ft3"] < 0].tolist()
    findings.append(Finding(
        "a. stop volume <= capacity",
        FAIL if over else OK,
        f"stops over capacity: {over}" if over
        else f"all stops fit; min volume slack {feas['volume_slack_ft3'].min():.0f} ft3",
    ))

    # (b) A stop that fails any time limit alone would need its orders split.
    infeasible = feas.index[~feas["feasible"]].tolist()
    tightest = feas[["drive_slack_min", "duty_slack_min", "span_slack_min"]].min()
    findings.append(Finding(
        "b. every stop feasible alone",
        FAIL if infeasible else OK,
        f"infeasible stops: {infeasible}" if infeasible
        else "all stops feasible alone; min slack (min): "
             + ", ".join(f"{c}={v:.1f}" for c, v in tightest.items()),
    ))

    # (c) Two indices that are the same place: 0 miles apart, or same global id.
    n = len(d)
    # np.triu_indices(n, 1) lists every pair (a, b) with a < b exactly once.
    a_idx, b_idx = np.triu_indices(n, 1)
    zero_pairs = [(int(a), int(b)) for a, b in zip(a_idx, b_idx) if d[a, b] == 0]
    dup_ids = inst.locations["GlobalLocationId"].duplicated(keep=False)
    dup_locs = inst.locations.index[dup_ids].tolist()
    findings.append(Finding(
        "c. no duplicate locations",
        WARN if (zero_pairs or dup_locs) else OK,
        f"0-mile pairs: {zero_pairs}; duplicate GlobalLocationId at: {dup_locs}"
        if (zero_pairs or dup_locs)
        else "no 0-mile pairs, GlobalLocationId unique",
    ))

    # (d) Shortcuts through a STOP: a route might want to pass through it again.
    via_stop = violations[violations["k"] != depot]
    findings.append(Finding(
        "d. no shortcuts through stops",
        WARN if len(via_stop) else OK,
        f"{len(via_stop)} cases; max saving {via_stop['excess_mi'].max():.0f} mi "
        f"({via_stop['excess_min'].max():.1f} min). Direct-arc model overstates "
        "these legs; a stop could be passed through more than once."
        if len(via_stop) else "no stop is a shortcut",
    ))

    # (e) Depot legs that are not shortest paths.
    depot_rows = violations[(violations["i"] == depot) | (violations["j"] == depot)]
    # The non-depot endpoint is whichever of i/j is not the depot.
    # Parentheses matter: "-" binds tighter than "|", so without them the depot
    # would only be removed from the j set.
    depot_stops = sorted((set(depot_rows["i"]) | set(depot_rows["j"])) - {depot})
    findings.append(Finding(
        "e. depot legs are shortest paths",
        WARN if len(depot_rows) else OK,
        f"{len(depot_rows)} cases, stops {depot_stops}; max saving "
        f"{depot_rows['excess_mi'].max():.0f} mi. DistanceFromDepot_mi overstates these."
        if len(depot_rows) else "all depot legs are shortest paths",
    ))

    # (f) Orders at one stop that need different vehicle types (matters in M2).
    kinds = inst.orders.groupby("LocationIndex")["RequiresStraightTruck"].nunique()
    mixed = kinds.index[kinds > 1].tolist()
    findings.append(Finding(
        "f. one vehicle type per stop (M2)",
        WARN if mixed else OK,
        f"stops mixing Straight-Truck-only and Van-OK orders: {mixed} "
        "(ignored in M1; in M2 these may need two visits)"
        if mixed else "every stop's orders share eligibility",
    ))
    return findings
