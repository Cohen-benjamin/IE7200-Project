"""Print a data audit of the Monday instance.

Run from the repo root:  python experiments/audit_report.py
All numbers come from dispatch.audit; this script only formats and prints.
"""
from pathlib import Path

import pandas as pd

from dispatch import audit
from dispatch.data import load_instance

# data/csv relative to this file, so the script runs from any folder.
DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "csv"


def section(title: str, assumption: str) -> None:
    """Print a section header and the modelling assumption it tests."""
    print("\n" + "=" * 78)
    print(title)
    print(f"Assumption tested: {assumption}")
    print("=" * 78)


def main(top_n: int = 10) -> None:
    """Load the instance, run every audit check, print a summary.

    Inputs:
        top_n: how many rows to show for "worst" and "most frequent" lists.
    Output:
        None (prints to the terminal).
    """
    inst = load_instance(DATA_DIR)
    # Show whole tables without pandas truncating columns.
    pd.set_option("display.width", 200)

    # 1. Triangle inequality
    viol = audit.triangle_violations(inst)
    counts = audit.violation_location_counts(viol)
    section("1. TRIANGLE-INEQUALITY VIOLATIONS",
            "distances are shortest paths (metric)")
    print(f"Violations (pair i<j, shortcut k): {len(viol)}")
    print(f"Distinct pairs affected: {viol[['i', 'j']].drop_duplicates().shape[0]}")
    print(f"\nWorst {top_n} by excess miles:")
    print(viol.head(top_n).to_string(index=False))
    print(f"\nLocations appearing most (top {top_n}):")
    print(counts.head(top_n).to_string())

    # 2. Per-location profile
    prof = audit.location_profile(inst)
    section("2. PER-LOCATION PROFILE",
            "each location fits one van on distance, volume and unload time")
    print(prof.round(2).to_string())

    # 3. Single-stop feasibility
    feas = audit.single_stop_feasibility(inst)
    section("3. SINGLE-STOP FEASIBILITY (depot -> s -> depot)",
            "every stop can be served alone, so the problem is feasible")
    print(f"Feasible alone: {int(feas['feasible'].sum())} of {len(feas)}")
    print("Tightest first (by drive slack):")
    print(feas.sort_values("drive_slack_min").round(2).to_string())

    # 4. One-visit-per-location validity
    section("4. 'ONE VISIT PER LOCATION' CHECKS",
            "visit each location once, deliver all its orders, drive direct arcs")
    for f in audit.one_visit_checks(inst, viol):
        print(f"[{f.status:4}] {f.check}: {f.detail}")


if __name__ == "__main__":
    main()
