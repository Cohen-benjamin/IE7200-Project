"""Run every solver option set on the full instance and on seeded subsets.

One command, from the repo root:   python experiments/run_benchmark.py   (about 2 minutes)

What it does
------------
1. FULL instance (34 stops): every option set of nearest neighbour (6) and
   Clarke-Wright (12). No optimum is known for 34 stops, so there is no gap.
2. SUBSETS of 8 and 9 stops (random and clustered, seeds fixed below): brute
   force gives the TRUE optimum, so each option set's gap to optimal is exact.
3. Every plan is saved to a temporary CSV and checked by validate_plan
   against its own (sub)instance BEFORE it is recorded. An invalid plan stops
   the run with an error; it is never written to the results.
Results: results/benchmark.csv (one row per plan) and results/benchmark.md
(tables). results/ is gitignored, so generated results are never committed.

Reading the gap: brute force is optimal among plans that keep each location's
orders on ONE van. Option sets that split orders (split=True) are outside that
scope and can occasionally beat it, giving a negative gap.

Units: miles, minutes, ft3; utilization in percent of each limit.
"""
import tempfile
from pathlib import Path

import pandas as pd

import sys

# Let "import dispatch" work without "pip install -e ." by adding the src/ folder to Python's search path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dispatch.data import FILE_PREFIX, load_instance
from dispatch.params import load_params
from dispatch.solvers import brute, clarke_wright, nearest_neighbor
from dispatch.validate import validate_plan

ROOT = Path(__file__).resolve().parent.parent  # project folder = two levels above this file
DATA_DIR = ROOT / "data" / "csv"  # where the instance CSVs live
RESULTS_DIR = ROOT / "results"                  # gitignored; NOT outputs/ (see module docstring)

# --- Settings: fixed so every run is identical (runtimes aside) ----------------
SEEDS = range(5)                                # subset seeds 0..4
SUBSET_SIZES = (8, 9)                           # stops per brute-force subset
MODES = ("random", "clustered")                 # how subsets are drawn
EXACT_CAP = 9                                   # max_exact_stops given to every solver
NN_SEQUENCING = ("nn", "nn_2opt", "exact")  # sequencing methods tried with nearest neighbour
NN_SPLIT = (False, True)  # orders kept together / allowed to split
CW_LAMBDAS = (0.5, 0.8, 1.0, 1.2, 1.5, 2.0)  # Clarke-Wright savings shapes tried
CW_RESEQUENCE = (False, True)  # keep merged order / re-order merged routes


def option_sets(cap: int = EXACT_CAP) -> list:
    """Every solver option set as a function: solve(instance) -> Solution.

    Inputs:
        cap: max_exact_stops given to each solver (route size cap for exact search).
    Output:
        list of 18 functions (6 nearest neighbour, 12 Clarke-Wright), in a
        fixed order. Each Solution's .method string records its options.
    """
    # Build one small function per option set; the benchmark calls each on the same data.
    fns = []
    # Nearest neighbour: 3 sequencing methods x 2 split options = 6 option sets.
    for seq in NN_SEQUENCING:
        for split in NN_SPLIT:
            # seq=seq, split=split bind THIS loop's values (otherwise every
            # function would see only the last ones).
            fns.append(lambda inst, seq=seq, split=split: nearest_neighbor.solve(
                inst, sequencing=seq, split_orders=split, max_exact_stops=cap))
    # Clarke-Wright: 6 lam values x 2 re-sequence options = 12 option sets.
    for lam in CW_LAMBDAS:
        for reseq in CW_RESEQUENCE:
            fns.append(lambda inst, lam=lam, reseq=reseq: clarke_wright.solve(
                inst, lam=lam, resequence=reseq, max_exact_stops=cap))
    return fns


def run_one(solve_fn, instance, params, tmp_dir) -> dict:
    """Solve, validate the saved plan, and measure it. Raises if the plan is invalid.

    Inputs:
        solve_fn: function instance -> Solution.
        instance: the (sub)instance to solve and to validate against.
        params: limits for the validator (read from the raw parameters CSV).
        tmp_dir: folder for the temporary plan file.
    Output:
        dict of results (method, routes, total miles, utilization avg/max,
        tightest drive and span slack, runtime, and "workload": the per-route
        DataFrame from Solution.summary_table()). valid is always True here:
        an invalid plan raises RuntimeError and is never recorded.
    """
    # Step 1: solve with this option set.
    sol = solve_fn(instance)
    # Validate the SAVED FILE with the independent validator, so what is
    # recorded is exactly what would be written to disk.
    # Step 2: save the plan, read it back, and check it with the independent validator.
    path = Path(tmp_dir) / "plan.csv"
    sol.to_csv(path, instance)
    problems = validate_plan(pd.read_csv(path), instance, params)
    # Any problem means the run stops: an invalid plan is never recorded.
    if problems:
        details = "\n".join(f"  route {v.route_id}: [{v.check}] {v.detail}" for v in problems)
        raise RuntimeError(f"{sol.method}: plan failed validation, not recorded:\n{details}")

    # Step 3: measure the valid plan: % of each limit used per route, and the least slack.
    util = sol.utilization()                       # % of each limit used, per route
    slack = sol.tightest_slack()["slack"]          # least room left per constraint
    # The headline numbers go into one dict = one row of the results table.
    row = {"method": sol.method, "routes": sol.n_routes, "total_miles": sol.total_miles}
    # Same two numbers (average and fullest route) for each of the four limits.
    for name in ("volume", "drive", "duty", "span"):
        row[f"avg_{name}_util"] = util[f"{name}_pct"].mean()   # average over routes
        row[f"max_{name}_util"] = util[f"{name}_pct"].max()    # the fullest route
    row["min_drive_slack"] = slack["drive"]
    row["min_span_slack"] = slack["span"]
    row["runtime_s"] = sol.runtime_s
    row["valid"] = True
    row["workload"] = sol.summary_table().iloc[:-1]    # one row per route (drop the total row)  # iloc[:-1] = every row but the last (the total row)
    return row


def run_benchmark(subset_sizes=SUBSET_SIZES, seeds=SEEDS, modes=MODES,
                  cap: int = EXACT_CAP, full_instance: bool = True) -> pd.DataFrame:
    """Run everything; one row per (instance or subset, method).

    Inputs:
        subset_sizes, seeds, modes: which brute-force subsets to draw.
        cap: max_exact_stops for every solver.
        full_instance: include the full 34-stop instance (False for quick tests).
    Output:
        DataFrame with scope ("full" or "subset"), k, mode, seed, the
        run_one columns, optimal_miles and gap_pct (subsets only; empty on full).
    """
    # Step 1: load the data and the limits once.
    inst = load_instance(DATA_DIR)
    params = load_params(DATA_DIR / f"{FILE_PREFIX}_parameters.csv")   # limits for the validator
    # Step 2: every result row is added to this list; it becomes the table at the end.
    rows = []
    workloads = []                                  # per-route tables of the full-instance plans
    with tempfile.TemporaryDirectory() as tmp:
        # --- Full instance: no optimum known, so no gap ----------------------
        # Part A: the whole 34-stop problem. No optimum is known, so there is no gap.
        if full_instance:
            for fn in option_sets(cap):
                result = run_one(fn, inst, params, tmp)
                workloads.append(result.pop("workload").assign(method=result["method"]))   # keep out of the row
                rows.append({"scope": "full", "k": len(inst.stops), "mode": "", "seed": "", **result})
        # --- Subsets: brute force is the reference --------------------------
        # Part B: small random or clustered subsets where brute force finds the true optimum.
        for k in subset_sizes:
            for mode in modes:
                for seed in seeds:
                    stops = brute.draw_subset(inst, k, seed, mode)  # pick k stops with a fixed seed (same every run)
                    sub = brute.restrict_instance(inst, stops)      # the subset's own problem
                    # Brute force first: its miles are the optimum for this subset.
                    best = run_one(lambda _s: brute.solve(inst, stops=stops), sub, params, tmp)  # the lambda ignores its input and solves this subset
                    group = [best] + [run_one(fn, sub, params, tmp) for fn in option_sets(cap)]  # brute force first, then every heuristic on the same subset
                    for r in group:
                        r.pop("workload")                       # per-route tables are kept for the full instance only
                        r["method"] = "brute (optimal)" if r["method"].startswith("brute") else r["method"]
                        r["optimal_miles"] = best["total_miles"]
                        r["gap_pct"] = (r["total_miles"] - best["total_miles"]) / best["total_miles"] * 100  # % above the optimum (0 = optimal)
                        rows.append({"scope": "subset", "k": k, "mode": mode, "seed": seed, **r})
    # Fixed column order, so the CSV looks the same every time.
    columns = ["scope", "k", "mode", "seed", "method", "routes", "total_miles",
               "avg_volume_util", "max_volume_util", "avg_drive_util", "max_drive_util",
               "avg_duty_util", "max_duty_util", "avg_span_util", "max_span_util",
               "min_drive_slack", "min_span_slack", "runtime_s", "optimal_miles", "gap_pct", "valid"]
    df = pd.DataFrame(rows).reindex(columns=columns)  # reindex keeps only these columns, in this order
    df.attrs["workloads"] = pd.concat(workloads, ignore_index=True) if workloads else None   # read by to_markdown / write_results
    return df


def _table(header: list, body: list) -> str:
    """A markdown table from a header row and a list of row lists."""
    # Line 1 = the header; line 2 = the |---| line that turns the text into a table.
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in body]
    return "\n".join(lines)  # glue the lines together, one per row


def to_markdown(df: pd.DataFrame, cap: int = EXACT_CAP) -> str:
    """The results as two markdown tables plus notes.

    Inputs:
        df: output of run_benchmark.
        cap: the exact-search cap used (stated in the notes).
    Output:
        markdown text: full-instance table (sorted by miles), subset table
        (sorted by mean gap), and notes on settings and how to read them.
    """
    parts = ["# Benchmark results", ""]  # the markdown is built as a list of text pieces, joined at the end

    full = df[df["scope"] == "full"].sort_values("total_miles", kind="stable")  # keep full-instance rows only; fewest miles first
    if len(full):
        parts += ["## Full instance (34 stops, 43 orders)", "",
                  "No optimum is known for 34 stops, so there is no gap column.", ""]
        parts.append(_table(
            ["Method", "Routes", "Total miles", "Avg / max volume util", "Tightest span slack (min)",
             "Tightest drive slack (min)", "Runtime (s)"],
            [[r.method, r.routes, f"{r.total_miles:.0f}",
              f"{r.avg_volume_util:.0f}% / {r.max_volume_util:.0f}%",
              f"{r.min_span_slack:.1f}", f"{r.min_drive_slack:.1f}", f"{r.runtime_s:.2f}"]
             for r in full.itertuples()]))
        parts.append("")
        work = df.attrs.get("workloads")
        if work is not None:
            best = full.iloc[0]["method"]               # lowest miles
            parts += [f"## Driver workload of the best plan ({best})", "",
                      "One row per route; the other plans are in `benchmark_workloads.csv`.", "",
                      _table(["Route", "Stops", "# stops", "Orders", "Miles", "Drive (min)", "Unload (min)",
                              "Duty (min)", "Span (min)", "Volume (ft3)", "Volume %", "Drive %", "Duty %", "Span %"],
                             [[r.route, r.stops.replace("-", " - "), r.n_stops, r.n_orders, f"{r.miles_total:.0f}",
                               f"{r.drive_min:.1f}", f"{r.unload_min:.1f}", f"{r.duty_min:.1f}", f"{r.span_min:.1f}",
                               f"{r.volume_ft3:.0f}", f"{r.volume_pct:.0f}%", f"{r.drive_pct:.0f}%",
                               f"{r.duty_pct:.0f}%", f"{r.span_pct:.0f}%"]
                              for r in work[work["method"] == best].itertuples()]), ""]

    sub = df[df["scope"] == "subset"]  # keep the brute-force subset rows only
    if len(sub):
        n_sets = sub.groupby(["k", "mode", "seed"]).ngroups
        body = []
        # One table row per method: g holds that method's results on all 20 subsets.
        for method, g in sub.groupby("method", sort=False):
            body.append((g["gap_pct"].mean(), [
                method, len(g), f"{g['gap_pct'].mean():.2f}%", f"{g['gap_pct'].max():.2f}%",
                f"{int((g['gap_pct'].abs() < 1e-9).sum())}/{len(g)}", f"{g['routes'].mean():.1f}",
                f"{g['min_span_slack'].min():.1f}", f"{g['min_drive_slack'].min():.1f}",
                f"{g['runtime_s'].mean():.3f}"]))
        body.sort(key=lambda t: t[0])                           # best (lowest mean gap) first  # sort by mean gap (best first)
        parts += [f"## Seeded brute-force subsets ({n_sets} subsets)", "",
                  "Gap = extra miles vs the true optimum found by brute force on the same subset.", ""]
        parts.append(_table(
            ["Method", "Subsets", "Mean gap", "Max gap", "Optimal", "Mean routes",
             "Tightest span slack (min)", "Tightest drive slack (min)", "Mean runtime (s)"],
            [row for _, row in body]))
        parts.append("")

    # Notes: the settings used and how to read the numbers.
    parts += ["## Notes", "",
              f"- Subsets: sizes {sorted(sub['k'].unique().tolist()) if len(sub) else []}, "
              f"modes {sorted(sub['mode'].unique().tolist()) if len(sub) else []}, "
              f"seeds {sorted(sub['seed'].unique().tolist()) if len(sub) else []} (all fixed).",
              f"- Exact-sequencing route cap: max_exact_stops = {cap} for every solver.",
              f"- All {len(df)} plans were saved to CSV and passed validate_plan before being recorded.",
              "- Brute force is optimal among plans that keep each location's orders on one van; "
              "split=True option sets can beat it (negative gap).",
              "- Utilization = used / limit per route; average and maximum over routes."]
    return "\n".join(parts) + "\n"


def write_results(df: pd.DataFrame, out_dir: Path = RESULTS_DIR, cap: int = EXACT_CAP) -> None:
    """Write benchmark.csv and benchmark.md into out_dir (created if needed)."""
    out_dir.mkdir(parents=True, exist_ok=True)  # create the folder if it is missing
    df.to_csv(out_dir / "benchmark.csv", index=False)
    (out_dir / "benchmark.md").write_text(to_markdown(df, cap), encoding="utf-8")
    work = df.attrs.get("workloads")
    if work is not None:                                # one row per route per full-instance plan
        work[["method"] + [c for c in work.columns if c != "method"]].to_csv(out_dir / "benchmark_workloads.csv", index=False)


def main() -> None:
    """Run the benchmark, write the files, print the tables."""
    df = run_benchmark()  # the whole benchmark, about 2 minutes
    write_results(df)
    print(to_markdown(df))
    print(f"Wrote benchmark.csv, benchmark.md and benchmark_workloads.csv in {RESULTS_DIR}")


# Runs only when the file is executed directly, not when a test imports it.
if __name__ == "__main__":
    main()
