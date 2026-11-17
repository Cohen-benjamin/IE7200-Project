"""Tests for dispatch.validate.validate_plan.

Plans are built with route.py's metrics as the "reported" numbers, so each
valid plan also cross-checks two independent implementations. Every plan
goes through a real CSV file and back. Units: miles, minutes, ft3.
"""
import ast
import dataclasses
from pathlib import Path

import pandas as pd
import pytest

from dispatch.ingest.data import FILE_PREFIX, load_instance
from dispatch.ingest.params import load_params
from dispatch.route import route_metrics
from dispatch.validate import METRIC_COLS, validate_plan

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "csv"
# Two stops chosen so one van carrying both exceeds the 3,200 ft3 capacity.
OVER_CAPACITY = [7, 15]                                    # 3,275 ft3 > 3,200
# A long route chosen so its span is above the 600-minute limit.
OVER_SPAN = [3, 12, 2, 1, 25, 11, 9, 8, 10, 5, 4, 6]       # span 675 > 600


# A fixture builds a value once and hands it to tests that ask for it by name; module = built once per file.
@pytest.fixture(scope="module")
def inst():
    return load_instance(DATA_DIR)


@pytest.fixture(scope="module")
def params():
    """Limits from the raw parameters CSV, as the validator expects."""
    return load_params(DATA_DIR / f"{FILE_PREFIX}_parameters.csv")


def plan_rows(routes, inst):
    """Plan table in visit order: depot row, one row per order, depot row."""
    # Build the plan the way solution.py writes it: depot row, one row per order, depot row.
    van, depot, rows = inst.params.vehicle("Van"), inst.depot_index, []
    for route_id, (stops, orders) in enumerate(routes, start=1):
        m = route_metrics(stops, orders, inst, van)  # route.py supplies the 'reported' numbers, so valid plans cross-check two implementations
        common = {"route_id": route_id, "vehicle": "Van", **{c: getattr(m, c) for c in METRIC_COLS}}
        rows.append({**common, "LocationIndex": depot, "OrderIndex": None})
        for s in stops:
            for o in orders:
                if inst.orders.loc[o, "LocationIndex"] == s:
                    rows.append({**common, "LocationIndex": s, "OrderIndex": o})
        rows.append({**common, "LocationIndex": depot, "OrderIndex": None})
    return pd.DataFrame(rows)


def check(df, inst, params, tmp_path):
    """Write the plan to CSV, read it back, validate; return {(route, code)}."""
    # Go through a real CSV file, as a submitted plan file would; tmp_path is a throw-away folder.
    df.to_csv(tmp_path / "plan.csv", index=False)
    v = validate_plan(pd.read_csv(tmp_path / "plan.csv"), inst, params)
    # A set of (route, problem-code) pairs makes 'exactly this problem and nothing else' easy to assert.
    return {(x.route_id, x.check) for x in v}, v


# A simple valid plan: one van per stop. skip leaves some stops out.
def singles(inst, skip=()):
    """One route per stop (every stop is feasible alone)."""
    return [([s], list(inst.orders_at[s])) for s in inst.stops if s not in skip]


def whole(inst, stops):
    return (stops, [o for s in stops for o in inst.orders_at[s]])


# --- valid plans ----------------------------------------------------------------

# The baseline: this plan must produce no violations at all.
def test_one_route_per_stop_is_valid(inst, params, tmp_path):
    assert check(plan_rows(singles(inst), inst), inst, params, tmp_path)[1] == []


# Location 7's two orders on two vans is legal, so the validator must accept it.
def test_split_stop_is_valid(inst, params, tmp_path):
    routes = singles(inst, skip=(4, 7)) + [([4, 7], [4, 10, 41]), ([7], [3])]
    assert check(plan_rows(routes, inst), inst, params, tmp_path)[1] == []


# --- negative tests (exactly the expected problem, nothing else) ----------------------

# Each negative test breaks the plan in ONE way and expects exactly that one code.
def test_duplicate_order(inst, params, tmp_path):
    codes, _ = check(plan_rows(singles(inst) + [([7], [3])], inst), inst, params, tmp_path)
    assert codes == {(None, "duplicate_order")}


def test_missing_order(inst, params, tmp_path):
    codes, v = check(plan_rows(singles(inst, skip=(14,)), inst), inst, params, tmp_path)
    assert codes == {(None, "missing_order")}
    assert "26" in v[0].detail and "42" in v[0].detail


def test_over_capacity(inst, params, tmp_path):
    routes = singles(inst, skip=OVER_CAPACITY) + [whole(inst, OVER_CAPACITY)]
    codes, v = check(plan_rows(routes, inst), inst, params, tmp_path)
    assert codes == {(len(routes), "volume")}
    assert "over by 75.00" in v[0].detail


def test_over_span(inst, params, tmp_path):
    routes = singles(inst, skip=OVER_SPAN) + [whole(inst, OVER_SPAN)]
    codes, v = check(plan_rows(routes, inst), inst, params, tmp_path)
    assert codes == {(len(routes), "span")}
    assert "over by 75.00" in v[0].detail


def test_missing_depot_end(inst, params, tmp_path):
    df = plan_rows(singles(inst), inst)
    df = df.drop(index=df[df["route_id"] == 1].index.max())     # drop route 1's last row  # remove the last row of route 1 (its return to the depot)
    assert check(df, inst, params, tmp_path)[0] == {(1, "depot_end")}


def test_misreported_metric(inst, params, tmp_path):
    df = plan_rows(singles(inst), inst)
    df.loc[df["route_id"] == 2, "miles_total"] += 1.0  # claim one extra mile on route 2 that the data does not support
    assert check(df, inst, params, tmp_path)[0] == {(2, "metric_mismatch")}


def test_params_argument_is_enforced(inst, params, tmp_path):
    # Shrink the working window to 20 minutes: every stop's unloading then breaks the span limit.
    tight = dataclasses.replace(params, window_end_min=params.window_start_min + 20)
    df = plan_rows(singles(inst), inst)
    df.to_csv(tmp_path / "plan.csv", index=False)
    v = validate_plan(pd.read_csv(tmp_path / "plan.csv"), inst, tight)
    assert {x.check for x in v} == {"span"} and len(v) == len(inst.stops)


# Independence check: read validate.py's own import lines (ast) and allow only the data and params loaders.
def test_validate_shares_no_code_with_solvers():
    """validate.py may import only the loader types from dispatch."""
    tree = ast.parse((ROOT / "src" / "dispatch" / "validate.py").read_text())
    mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    mods |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert {m for m in mods if m.startswith("dispatch")} <= {"dispatch.ingest.data", "dispatch.ingest.params"}


def test_unload_formula_must_match_the_data_file(inst, params, tmp_path):
    # Pretend the data file says order 26 takes 10 minutes longer than the formula gives.
    orders = inst.orders.copy()
    orders.loc[26, "UnloadTime_min"] += 10
    changed = dataclasses.replace(inst, orders=orders)
    df = plan_rows(singles(inst), inst)                  # the plan itself is unchanged and valid
    codes, v = check(df, changed, params, tmp_path)
    assert codes == {(14, "unload_vs_data")}             # order 26 is on the route for location 14
    assert "data file UnloadTime_min" in v[0].detail
