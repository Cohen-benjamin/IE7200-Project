"""Measure each sequencing rung against the exact optimum on small stop sets.

Run from the repo root:  python experiments/sequencing_ladder.py
For k = 5..9 stops, the exact solver gives the true best order, so each
heuristic rung's error can be measured exactly (brief section 4.1).
Prints one row per (k, method). Runtime: about 1-2 minutes (k = 9 dominates).
"""
import time
from pathlib import Path

import pandas as pd

from dispatch.data import Instance, load_instance
from dispatch.sequencing import exact_sequence, METHODS

# data/csv relative to this file, so the script runs from any folder.
DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "csv"
# Heuristic rungs to compare, in ladder order (exact is the reference).
RUNGS = ["nn", "nn_2opt"]


def candidate_sets(inst: Instance, k: int) -> list[tuple[int, ...]]:
    """Route-like stop sets of size k: each stop plus its k-1 nearest stops.

    Inputs:
        inst: problem instance.
        k: stops per set.
    Output:
        sorted, de-duplicated list of sorted stop tuples (at most 34 sets).
        Deterministic; random sets would mostly mix far-apart stops and be
        infeasible for every method, which measures nothing.
    """
    d = inst.dist_mi
    sets = set()
    for seed in inst.stops:
        # Sort all stops by distance from the seed (the seed itself is 0 mi).
        nearest = sorted(inst.stops, key=lambda s: (d[seed, s], s))[:k]
        sets.add(tuple(sorted(nearest)))
    return sorted(sets)


def run_ladder(inst: Instance, k_values=range(5, 10)) -> pd.DataFrame:
    """Run exact + every rung on every candidate set; one row per call.

    Inputs:
        inst: problem instance.
        k_values: set sizes to test (exact is run with max_exact_stops = k).
    Output:
        DataFrame with columns k, stops, method, feasible, miles,
        exact_feasible, exact_miles, ms, evaluations, orders_scored.
    """
    van = inst.params.vehicle("Van")
    rows = []
    for k in k_values:
        for stops in candidate_sets(inst, k):
            orders = [o for s in stops for o in inst.orders_at[s]]
            # Reference: the proven best order (or proof of infeasibility).
            t0 = time.perf_counter()
            ex = exact_sequence(stops, orders, inst, van, max_exact_stops=k)
            ex_ms = (time.perf_counter() - t0) * 1000
            ref = {"exact_feasible": ex.sequence is not None,
                   "exact_miles": ex.metrics.miles_total if ex.sequence else None}
            rows.append({"k": k, "stops": stops, "method": "exact",
                         "feasible": ex.sequence is not None,
                         "miles": ex.metrics.miles_total if ex.sequence else None,
                         "ms": ex_ms, "evaluations": ex.evaluations,
                         "orders_scored": ex.orders_scored, **ref})
            for name in RUNGS:
                t0 = time.perf_counter()
                r = METHODS[name](stops, orders, inst, van)
                ms = (time.perf_counter() - t0) * 1000
                rows.append({"k": k, "stops": stops, "method": name,
                             "feasible": r.sequence is not None,
                             "miles": r.metrics.miles_total if r.sequence else None,
                             "ms": ms, "evaluations": r.evaluations,
                             "orders_scored": r.orders_scored, **ref})
    return pd.DataFrame(rows)


def summarise(raw: pd.DataFrame) -> pd.DataFrame:
    """One row per (k, method) with the ladder statistics.

    Inputs:
        raw: output of run_ladder.
    Output:
        DataFrame with: sets, exact_feasible (sets with a legal order),
        found_pct (share of those the method also found), false_rejections
        (legal sets the method reported infeasible), mean_gap_pct and
        max_gap_pct (extra miles vs exact, where both are feasible),
        mean_ms, mean_evaluations, mean_orders_scored.
    """
    out = []
    for (k, method), g in raw.groupby(["k", "method"], sort=False):
        legal = g[g["exact_feasible"]]
        both = legal[legal["feasible"]]
        gap = (both["miles"] - both["exact_miles"]) / both["exact_miles"] * 100
        out.append({
            "k": k, "method": method,
            "sets": len(g),
            "exact_feasible": len(legal),
            "found_pct": 100 * len(both) / len(legal) if len(legal) else float("nan"),
            "false_rejections": len(legal) - len(both),
            "mean_gap_pct": gap.mean() if len(gap) else float("nan"),
            "max_gap_pct": gap.max() if len(gap) else float("nan"),
            "mean_ms": g["ms"].mean(),
            "mean_evaluations": g["evaluations"].mean(),
            "mean_orders_scored": g["orders_scored"].mean(),
        })
    return pd.DataFrame(out)


def main() -> None:
    """Load the instance, run the ladder, print the summary table."""
    inst = load_instance(DATA_DIR)
    table = summarise(run_ladder(inst))
    pd.set_option("display.width", 200)
    print(table.round(2).to_string(index=False))


if __name__ == "__main__":
    main()
