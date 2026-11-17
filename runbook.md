# Runbook

## 1. Environment
- **Python 3.11 or newer** (results were produced on 3.12.0). pandas 3 and numpy 2.5 do not support 3.10.
- **Pinned packages** in `requirements.txt`: numpy 2.5.4, pandas 3.1.1, pytest 9.2.0.
- Set up once, from the project folder:

| Step | Windows (PowerShell) | macOS / Linux |
|---|---|---|
| Make a clean environment | `python -m venv .venv` | `python3 -m venv .venv` |
| Turn it on | `.venv\Scripts\Activate.ps1` | `source .venv/bin/activate` |
| Install the pinned packages | `pip install -r requirements.txt` | `pip install -r requirements.txt` |

No `pip install -e .` is needed: the scripts and pytest add `src/` to Python's search path themselves.

## 2. Weekly workflow
1. **Data.** Put the instance CSVs in `data/csv/` (`ie7200_Mon_parameters.csv`, `_locations.csv`, `_orders.csv`,
   `_distance_matrix.csv`, ...). Limits (capacity, 660 / 840 / 600 min, speed) come only from the parameters CSV.
2. **Audit the data** (optional): `python experiments/audit_report.py` prints the data checks recorded in `DATA_FINDINGS.md`.
   **Check the data and the code:** `pytest`. Data tests recompute totals from the raw files; `tests/test_plans.py`
   solves the instance with all 8 default methods and re-validates every route (4 limits, each order delivered exactly once).
3. **Make a plan:** `python experiments/run_selection.py` (choose solver / sequencing / splitting in the CHOOSE HERE
   block or with flags; `--all` runs the 8 default combinations). Each plan is validated before it is saved.
4. **Compare methods:** `python experiments/run_benchmark.py` (about 3 minutes): the 40 option sets on the full
   instance and on 40 stored 9-stop brute-force subsets (20 clustered, 20 random), where the true optimum is known.
5. **Read the results** in `results/` (gitignored): `<selection>/routes.csv` + `summary.md` (miles, routes,
   runtime, driver workload per route), `benchmark.md` / `.csv`, `benchmark_workloads.csv`.
6. **Record** new data quirks in `DATA_FINDINGS.md` and AI-assisted work in `AI_USAGE.md`.

**Reproducibility:** solvers are deterministic (ties broken by the lower index). The benchmark subsets are stored in
`data/benchmark_subsets_k9.csv` and read from it, so no random numbers are drawn at run time; `experiments/make_subsets.py`
shows how the file was made. Two runs give identical tables except the runtime columns.

## 3. Known limitations
- **Milestone 1 scope:** one homogeneous Van fleet. `RequiresStraightTruck`, dock waves and break rules (M2 and
  the original case) are ignored, so the course's `Solution_Check.xlsm` is a cross-check only.
- **File names are fixed** to the `ie7200_Mon` prefix (`FILE_PREFIX` in `src/dispatch/ingest/data.py`); another day needs that changed.
- **No optimality gap for the full 34-stop problem.** Brute force stops at 10 stops (Bell number growth); the gap is
  only measured on subsets.
- **Heuristics:** nearest neighbour is greedy and myopic (about 300 miles worse than Clarke-Wright); `nn_2opt`
  is span-aware but still a local search (it can miss a legal order); exact sequencing is opt-in (`--with-exact`, not benchmarked: 1-6 minutes per full run, never best) and, like brute force,
  capped at 10 stops (exact on 10 stops takes about 21 s; a 10-stop brute-force subset about 1 minute).
- **Distance matrix is not metric** (270 triangle violations): legs are charged as given, never shortened.
- **Unload times** are recomputed as max(30, 0.03 x volume) per order and cross-checked against the data file's
  `UnloadTime_min` (within 0.006 per order). Editing the unload rows in the parameters CSV makes every plan fail
  that cross-check.
- **Depot:** the data's depot is ZIP 01887 (Wilmington), not "Ayer" as the brief says (DATA_FINDINGS.md).
- **Clarke-Wright with order splitting** can strand an order: it can only join a route at the route's ends, so an order whose
  location is already an inner stop of a route may drive its own round trip (worst on low lam; see the split rows in `results/benchmark.md`).
  Splitting is off by default; no Monday location needs it.
- **Nearest neighbour with `nn_2opt`, orders together, is 2,030 miles on the full instance** (1,888 with plain `nn`): with span-aware 2-opt,
  stops that plain `nn` refuses now fit and change the greedy construction. The cause was not analysed further.
- **Not committed:** `results/` is gitignored; re-run the commands in section 2 to regenerate it.
