"""Run ONE chosen combination of route-selection and sequencing methods and
save its routes and results. Built so a reader can change the methods and
re-run without touching the solver code.

How to use
----------
1. Edit the settings in the "CHOOSE HERE" block below, then run:
       python experiments/run_selection.py
2. Or leave the file alone and pass flags, for example:
       python experiments/run_selection.py --solver nearest_neighbor --sequencing exact --split-orders
3. Run every combination (2 solvers x 3 sequencing x together/split = 12):
       python experiments/run_selection.py --all
   Or print the 12 command lines and run them one at a time:
       python experiments/run_selection.py --list

What you get (per selection) in results/<solver>_<sequencing>_<together|split>/
    routes.csv   the plan in the validator's format (every route, stop and order)
    summary.md   the settings used, total miles, utilization, tightest limits,
                 the validation verdict and a table of every route
Every plan is saved, then re-checked by validate_plan against the raw data
BEFORE anything is kept: an invalid plan stops the run and writes nothing.
--all also writes results/all_selections.md and .csv (ranked by miles).

Adding a solver: write solvers/<name>.py with solve(instance, ...), add it to
SOLVERS below and give it a branch in solve_selection.

Units: miles, minutes, ft3; utilization in percent of each limit.
"""
import argparse
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

import sys

# Let "import dispatch" work without "pip install -e ." by adding the src/ folder to Python's search path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dispatch.ingest.data import FILE_PREFIX, load_instance
from dispatch.ingest.params import load_params
from dispatch.solvers import clarke_wright, nearest_neighbor
from dispatch.validate import validate_plan

ROOT = Path(__file__).resolve().parent.parent  # project folder = two levels above this file
DATA_DIR = ROOT / "data" / "csv"  # where the instance CSVs live
RESULTS_DIR = ROOT / "results"                  # gitignored; results are never committed

# ============================ CHOOSE HERE ====================================
SOLVER = "clarke_wright"      # route selection: "nearest_neighbor" or "clarke_wright"
SEQUENCING = "nn_2opt"        # how a route's stops are ordered: "nn", "nn_2opt" (or "exact": very slow, opt-in)
SPLIT_ORDERS = False          # True = the orders at one location may go on different vans
# Clarke-Wright only:
LAM = 1.0                     # savings shape; 1.0 = the textbook formula
RESEQUENCE = True             # True = re-order each merged route with SEQUENCING;
                              # False = keep its end-to-end order (SEQUENCING is then ignored)
EXACT_CAP = 10                # largest route (in stops) that "exact" sequencing will solve
# =============================================================================

# The route-selection methods available.
SOLVERS = {"nearest_neighbor": nearest_neighbor, "clarke_wright": clarke_wright}
# What --all and --list run.
ALL_SOLVERS = tuple(SOLVERS)  # tuple of a dict = its keys (both solver names)
ALL_SEQUENCING = ("nn", "nn_2opt")                  # the sequencing methods --all / --list run by default
# "exact" tries every visit order: 1 to 6 minutes per full run, and it never beat nn_2opt, so it is opt-in (--with-exact).
OPTIONAL_SEQUENCING = ("exact",)
ALL_SPLIT = (False, True)


# A dataclass writes __init__ for us.
# frozen=True: the fields cannot be changed after creation.
@dataclass(frozen=True)
class Selection:
    """One combination of options (frozen: it cannot change after creation)."""

    solver: str  # which route-selection method
    sequencing: str  # how each route's stops are ordered
    split_orders: bool  # True = one location's orders may use different vans
    lam: float = 1.0  # Clarke-Wright savings shape (ignored by nearest neighbour)
    resequence: bool = True  # Clarke-Wright: re-order merged routes?
    exact_cap: int = 9  # largest route (stops) the exact method will solve

    # @property: use it like a field (sel.folder), without brackets.
    @property
    def uses_sequencing(self) -> bool:
        """False only for Clarke-Wright with resequence off (SEQUENCING is then ignored)."""
        # Nearest neighbour always uses the sequencing method;
        # Clarke-Wright only when it re-orders its merged routes.
        return self.solver == "nearest_neighbor" or self.resequence

    @property
    def folder(self) -> str:
        """Folder name for this selection, e.g. 'clarke_wright_nn_2opt_together'."""
        # Build the folder name from the settings; they are joined with underscores below.
        parts = [self.solver, self.sequencing if self.uses_sequencing else "asis",
                 "split" if self.split_orders else "together"]
        # lam only matters for Clarke-Wright; show it in the name only when it is not the default.
        if self.solver == "clarke_wright" and self.lam != 1.0:
            parts.append(f"lam{self.lam:g}")
        return "_".join(parts)  # glue the parts together: clarke_wright_nn_2opt_together

    def command(self) -> str:
        """The exact command line that reproduces this selection."""
        # Build the command text piece by piece, so it can be copied and re-run exactly.
        cmd = (f"python experiments/run_selection.py --solver {self.solver} --sequencing {self.sequencing} "
               f"--{'split-orders' if self.split_orders else 'no-split-orders'}")
        if self.solver == "clarke_wright":
            cmd += f" --lam {self.lam:g} --{'resequence' if self.resequence else 'no-resequence'}"
        return cmd + f" --exact-cap {self.exact_cap}"  # the cap is last because every solver takes it


def solve_selection(sel: Selection, instance):
    """Run the chosen solver with the chosen options.

    Inputs:
        sel: the combination of options.
        instance: the problem instance.
    Output:
        a Solution (routes plus numbers). Raises ValueError for an unknown solver.
    """
    # Pass each option on to the chosen solver. Both solvers share the same solve() shape.
    if sel.solver == "nearest_neighbor":
        return nearest_neighbor.solve(instance, sequencing=sel.sequencing,
                                      split_orders=sel.split_orders, max_exact_stops=sel.exact_cap)
    if sel.solver == "clarke_wright":
        return clarke_wright.solve(instance, lam=sel.lam, resequence=sel.resequence,
                                   sequencing=sel.sequencing, split_orders=sel.split_orders,
                                   max_exact_stops=sel.exact_cap)
    # Only reached when the name matches neither solver.
    raise ValueError(f"unknown solver {sel.solver!r}; choose from {sorted(SOLVERS)}")


def _md_table(header: list, rows: list) -> str:
    """A markdown table from a header row and a list of row lists."""
    # Line 1 = the header; line 2 = the |---| line that turns the text into a table.
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    # One line per data row; str() lets numbers and text share a table.
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)  # glue the lines together, one per row


def summary_markdown(sel: Selection, sol, n_orders: int) -> str:
    """The summary.md text for one validated plan.

    Inputs:
        sel: the options used.
        sol: the Solution.
        n_orders: orders in the instance (stated in the validation line).
    Output:
        markdown: settings, results, tightest limits, validation verdict, routes.
    """
    util = sol.utilization()                             # % of each limit used, per route
    slack = sol.tightest_slack()                         # least room left per constraint
    # Settings table: each row is [name, value].
    settings = [["Route selection (solver)", sel.solver],
                ["Sequencing", sel.sequencing + ("" if sel.uses_sequencing else " (ignored: resequence is off)")],
                ["Orders at one location", "may be split across vans" if sel.split_orders else "kept together"]]
    # Only Clarke-Wright has these two options, so only show them for it.
    if sel.solver == "clarke_wright":
        settings += [["lam (savings shape)", f"{sel.lam:g}"],
                     ["Re-sequence merged routes", "yes" if sel.resequence else "no (keep end-to-end order)"]]
    settings.append(["Exact-sequencing route cap", f"{sel.exact_cap} stops"])

    # Headline numbers. f'{x:.0f}' prints x with 0 decimals; :.1f gives 1 decimal.
    results = [["Routes", sol.n_routes], ["Total miles", f"{sol.total_miles:.0f}"],
               ["Volume utilization (avg / max)", f"{util['volume_pct'].mean():.0f}% / {util['volume_pct'].max():.0f}%"],
               ["Drive utilization (avg / max)", f"{util['drive_pct'].mean():.0f}% / {util['drive_pct'].max():.0f}%"],
               ["Duty utilization (avg / max)", f"{util['duty_pct'].mean():.0f}% / {util['duty_pct'].max():.0f}%"],
               ["Span utilization (avg / max)", f"{util['span_pct'].mean():.0f}% / {util['span_pct'].max():.0f}%"],
               ["Runtime", f"{sol.runtime_s:.2f} s"]]

    # One row per limit: how much room is left and on which route (iterrows gives label + row).
    limits = [[name, f"{row.slack:.1f}", int(row.route_id)] for name, row in slack.iterrows()]

    # Driver workload: one row per route plus a Total row, straight from Solution.summary_table().
    routes = []
    for _, r in sol.summary_table().iterrows():
        is_total = r["route"] == "total"                 # the total row has no stops, span or % (they don't add up)
        routes.append([r["route"], "" if is_total else r["stops"].replace("-", " - "), int(r["n_stops"]),
                       int(r["n_orders"]), f"{r['miles_total']:.0f}", f"{r['drive_min']:.1f}",
                       f"{r['unload_min']:.1f}", f"{r['duty_min']:.1f}",
                       "" if is_total else f"{r['span_min']:.1f}", f"{r['volume_ft3']:.0f}",
                       "" if is_total else f"{r['volume_pct']:.0f}%", "" if is_total else f"{r['drive_pct']:.0f}%",
                       "" if is_total else f"{r['duty_pct']:.0f}%", "" if is_total else f"{r['span_pct']:.0f}%"])

    # Stack every section (heading, blank line, table) into one text, in reading order.
    return "\n".join([
        f"# Results: {sol.method}", "", "## Settings", "", _md_table(["Setting", "Value"], settings), "",
        "## Results", "", _md_table(["Measure", "Value"], results), "",
        "## Tightest limits (smallest slack over all routes)", "",
        _md_table(["Constraint", "Slack (ft3 or min)", "Route"], limits), "",
        "## Validation", "",
        f"**VALID.** routes.csv was saved and re-checked by validate_plan against the raw data: all {n_orders} "
        "orders delivered exactly once, all four limits met on every route, and the reported numbers match "
        "the recomputed ones.", "",
        "## Driver workload (one row per route; stops in visit order, depot at both ends)", "",
        _md_table(["Route", "Stops", "# stops", "Orders", "Miles", "Drive (min)", "Unload (min)", "Duty (min)",
                   "Span (min)", "Volume (ft3)", "Volume %", "Drive %", "Duty %", "Span %"], routes), "",
        f"Reproduce: `{sel.command()}`", ""])


def run_selection(sel: Selection, instance, params, out_dir: Path) -> dict:
    """Solve, validate the saved plan, then write routes.csv and summary.md.

    Inputs:
        sel: the options to run.
        instance: the problem instance.
        params: limits for the validator (read from the raw parameters CSV).
        out_dir: folder that will contain this selection's own sub-folder.
    Output:
        dict with the headline numbers (for the comparison table).
        Raises RuntimeError if the plan is invalid; in that case nothing is written.
    """
    # Step 1: solve.
    sol = solve_selection(sel, instance)
    # Validate the SAVED FILE (in a temporary folder) before keeping anything.
    with tempfile.TemporaryDirectory() as tmp:
        sol.to_csv(Path(tmp) / "routes.csv", instance)
        problems = validate_plan(pd.read_csv(Path(tmp) / "routes.csv"), instance, params)
    # Step 2: any problem means stop here, before anything is written.
    if problems:
        details = "\n".join(f"  route {v.route_id}: [{v.check}] {v.detail}" for v in problems)
        raise RuntimeError(f"{sel.folder}: plan failed validation, nothing written:\n{details}")

    folder = Path(out_dir) / sel.folder                    # valid: now it is safe to write
    folder.mkdir(parents=True, exist_ok=True)
    sol.to_csv(folder / "routes.csv", instance)
    (folder / "summary.md").write_text(summary_markdown(sel, sol, len(instance.orders)), encoding="utf-8")

    util = sol.utilization()
    slack = sol.tightest_slack()["slack"]
    # Step 3: hand the headline numbers back (used for the --all ranking).
    return {"solver": sel.solver, "sequencing": sel.sequencing if sel.uses_sequencing else "asis",
            "split_orders": sel.split_orders, "routes": sol.n_routes, "total_miles": sol.total_miles,
            "avg_volume_util": util["volume_pct"].mean(), "max_volume_util": util["volume_pct"].max(),
            "min_span_slack": slack["span"], "min_drive_slack": slack["drive"],
            "runtime_s": sol.runtime_s, "folder": sel.folder}


def grid(base: Selection, with_exact: bool = False) -> list:
    """Every combination for --all / --list: solvers x sequencing x together/split.

    Inputs:
        base: supplies lam, resequence and exact_cap for every combination.
        with_exact: also include the slow "exact" sequencing (default: skipped).
    Output:
        list of Selections without duplicates (Clarke-Wright with resequence
        off ignores sequencing, so it appears once per split option).
    """
    seen, out = set(), []  # seen = folders already added; out = the result list
    # Optional methods are added to the default list only when asked for.
    sequencing_methods = ALL_SEQUENCING + (OPTIONAL_SEQUENCING if with_exact else ())
    # Three nested loops = every pairing of solver, sequencing and split option.
    for solver in ALL_SOLVERS:
        for seq in sequencing_methods:
            for split in ALL_SPLIT:
                sel = Selection(solver, seq, split, base.lam, base.resequence, base.exact_cap)
                if sel.folder not in seen:                 # skip repeats (same folder = same run)
                    seen.add(sel.folder)
                    out.append(sel)
    return out


def comparison_markdown(rows: list) -> str:
    """The all_selections.md text: every run, ranked by total miles."""
    ranked = sorted(rows, key=lambda r: r["total_miles"])  # fewest miles first
    # One table row per run; i + 1 turns the 0-based position into rank 1, 2, 3, ...
    body = [[i + 1, r["solver"], r["sequencing"], "split" if r["split_orders"] else "together", r["routes"],
             f"{r['total_miles']:.0f}", f"{r['avg_volume_util']:.0f}% / {r['max_volume_util']:.0f}%",
             f"{r['min_span_slack']:.1f}", f"{r['min_drive_slack']:.1f}", f"{r['runtime_s']:.2f}", r["folder"]]
            for i, r in enumerate(ranked)]
    return "\n".join(["# All selections, ranked by total miles", "",
                      _md_table(["Rank", "Solver", "Sequencing", "Orders", "Routes", "Total miles",
                                 "Avg / max volume util", "Tightest span slack (min)",
                                 "Tightest drive slack (min)", "Runtime (s)", "Folder"], body), "",
                      f"All {len(rows)} plans were saved and passed validate_plan before being recorded. "
                      "Each folder holds routes.csv and summary.md.", ""])


def build_parser() -> argparse.ArgumentParser:
    """Command-line flags; every default comes from the CHOOSE HERE block."""
    # argparse reads the flags typed after the script name (--solver ...).
    p = argparse.ArgumentParser(description="Run one route-selection + sequencing combination "
                                            "(or all of them) and save routes and results.")
    # Each add_argument is one flag. Its default is the CHOOSE HERE value,
    # so a flag only overrides the block.
    p.add_argument("--solver", choices=sorted(SOLVERS), default=SOLVER)
    p.add_argument("--sequencing", choices=["nn", "nn_2opt", "exact"], default=SEQUENCING)
    # BooleanOptionalAction creates both --split-orders and --no-split-orders.
    p.add_argument("--split-orders", action=argparse.BooleanOptionalAction, default=SPLIT_ORDERS,
                   help="allow the orders at one location on different vans")
    p.add_argument("--lam", type=float, default=LAM, help="Clarke-Wright savings shape")
    p.add_argument("--resequence", action=argparse.BooleanOptionalAction, default=RESEQUENCE,
                   help="Clarke-Wright: re-order merged routes with the sequencing method")
    p.add_argument("--exact-cap", type=int, default=EXACT_CAP, help="largest route solved exactly")
    # store_true = a flag with no value: present means True.
    p.add_argument("--all", action="store_true", help="run every combination (without the slow exact sequencing)")
    p.add_argument("--with-exact", action="store_true", help="include the slow exact sequencing in --all / --list")
    p.add_argument("--list", action="store_true", help="print the command line of every combination")
    p.add_argument("--data-dir", type=Path, default=DATA_DIR, help="folder with the instance CSVs")
    p.add_argument("--out-dir", type=Path, default=RESULTS_DIR, help="where results are written")
    return p


def main(argv=None) -> list:
    """Parse flags and run. Returns the result rows (one per selection run)."""
    args = build_parser().parse_args(argv)  # typed flags become args.solver, args.lam, ...
    base = Selection(args.solver, args.sequencing, args.split_orders, args.lam, args.resequence, args.exact_cap)  # the one selection the flags describe

    if args.list:                                          # just print the commands
        for sel in grid(base, args.with_exact):
            print(sel.command())
        return []

    # Step 1: load the data once; every run reuses it.
    inst = load_instance(args.data_dir)
    params = load_params(Path(args.data_dir) / f"{FILE_PREFIX}_parameters.csv")   # limits for the validator
    selections = grid(base, args.with_exact) if args.all else [base]  # --all = 8 runs (12 with --with-exact), otherwise one
    if not args.all and not base.uses_sequencing:
        print("Note: --no-resequence is on, so the sequencing setting is ignored for Clarke-Wright.")

    # Step 2: run each selection. Each run validates its own plan first.
    rows = []
    for sel in selections:
        row = run_selection(sel, inst, params, args.out_dir)
        rows.append(row)
        print(f"{sel.folder}: {row['routes']} routes, {row['total_miles']:.0f} miles, "
              f"{row['runtime_s']:.1f} s, VALID -> {Path(args.out_dir) / sel.folder}")
    # Step 3: for --all, also save the ranking (fewest miles first).
    if args.all:
        out = Path(args.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows).sort_values("total_miles", kind="stable").to_csv(out / "all_selections.csv", index=False)
        (out / "all_selections.md").write_text(comparison_markdown(rows), encoding="utf-8")
        print(f"\nWrote {out / 'all_selections.md'} and {out / 'all_selections.csv'}")
    return rows


# Runs only when the file is executed directly, not when a test imports it.
if __name__ == "__main__":
    main()
