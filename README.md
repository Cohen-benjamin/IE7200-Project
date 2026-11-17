# monday-dispatch (IE7200 Project)

Vehicle routing / dispatch for the IE7200 Monday instance.

## Setup (Python 3.11+, tested on 3.12; pinned versions)
```bash
python -m venv .venv
.venv\Scripts\activate           # macOS / Linux: source .venv/bin/activate
pip install -r requirements.txt    # numpy 2.5.4, pandas 3.1.1, pytest 9.2.0
```

## One-line reproduction
```bash
python experiments/run_benchmark.py
```
Prints the results table (nearest neighbour vs Clarke-Wright on the full instance, and both vs brute force on 40
stored 9-stop subsets: 20 clustered, 20 random) and writes it to `results/benchmark.md` / `.csv`. The subsets are read
from a stored file (see "Benchmark subsets" below), so every run gives the same numbers (runtimes aside).

NOTE: Runtime is 4-6 minutes on benchmark due to Brute Force

## Other commands
```bash
pytest                                           # all tests, incl. re-validation of every route
python experiments/run_selection.py              # ONE selection (settings at the top of the file)
python experiments/run_selection.py --all        # all 8 default combinations, a few seconds
python experiments/run_selection.py --all --with-exact   # adds the 4 slow exact-sequencing runs, about 10 minutes
```

## Benchmark subsets (how the repeatable test sets work)
Brute force can only solve small problems, so the benchmarks compare every method with brute force on **40 stored subsets
of 9 stops each**: 20 clustered (a stop plus its nearest stops, like a real route) and 20 random.

- **The subsets live in `data/benchmark_subsets_k9.csv`** (committed). Columns: `subset_id` (0-39), `kind` (`clustered` or
  `random`), `k` (always 9), `stops` (the nine LocationIndex values, separated by spaces), `source` (the cluster centre or
  the random seed that produced the group).
- **`run_benchmark.py` only reads this file.** It draws no random numbers, so the results do not
  depend on Python's random generator or on any seed. Each run checks that every row has 9 distinct valid stops and stops
  with an error otherwise.
- **How the file was made:** `python experiments/make_subsets.py`.
  - *Clustered:* every stop is tried as a cluster centre, the 9 nearest stops are kept (ties go to the lower LocationIndex)
    and repeated groups are dropped. Only the distance matrix is used. For 9 stops this data has exactly 20 different clustered groups.
  - *Random:* seeds 0, 1, 2, ... each give one random group of 9; a group already used is skipped until there are 20.
- **To regenerate** the file (not needed to reproduce the results): run `python experiments/make_subsets.py`. On the pinned
  Python (3.12) it writes an identical file. The committed CSV, not the script, is the source of truth.
- **To use different subsets:** change `K` or `N_RANDOM` at the top of `make_subsets.py` (the clustered count is however many different groups exist for that `K`; brute force is
  limited to 10 stops per subset and takes about 4 seconds at 9), run it, then re-run the benchmarks. Do not edit the CSV by
  hand unless you mean to change the test sets.
- **Output columns:** in `results/benchmark.csv`, `mode` is the subset's kind and
  `seed` is its `subset_id` in the file.

## Changing the methods (no solver code to edit)
Open `experiments/run_selection.py` and edit the **CHOOSE HERE** block at the top, or pass flags:

| Setting | Choices | Flag |
|---|---|---|
| `SOLVER` (route selection) | `nearest_neighbor`, `clarke_wright` | `--solver` |
| `SEQUENCING` (order of a route's stops) | `nn`, `nn_2opt`, `exact` | `--sequencing` |
| `SPLIT_ORDERS` | `False` = a location's orders stay on one van, `True` = they may be split | `--split-orders` / `--no-split-orders` |
| `LAM`, `RESEQUENCE` (Clarke-Wright only) | savings shape, re-order merged routes | `--lam`, `--resequence` / `--no-resequence` |

Each run writes `results/<solver>_<sequencing>_<together|split>/routes.csv` (every route) and `summary.md`
(the folder says `asis` instead of the sequencing name when re-sequencing is off, and ends in `_lam<x>` when lam is not 1)
(miles, routes, runtime, utilization, tightest limits, and a driver-workload table: drive, unload, duty and span minutes per route). **Every plan is re-checked against the raw data by the
independent validator before it is saved.** `--list` prints the 8 default command lines to run one by one (12 with `--with-exact`).
The limits (capacity, 660 / 840 / 600 minutes, speed) are rows of
`data/csv/ie7200_Mon_parameters.csv`; edit a row and re-run to see the effect. Do not edit the unload rows: the validator cross-checks them against the data file.

See `runbook.md` for the environment, weekly workflow and known limitations, and `results/benchmark.md` (written by `run_benchmark.py`) for the measured results of every method.

## Layout
| Role | Path | Purpose |
|---|---|---|
| **Data** | `data/csv/` | Monday instance CSVs (`ie7200_Mon_*.csv`) |
| | `data/benchmark_subsets_k9.csv` | The 40 stored benchmark subsets (see "Benchmark subsets") |
| **Data ingestion** | `src/dispatch/ingest/params.py` | `Params`, `VehicleType` dataclasses, read from the parameters CSV |
| | `src/dispatch/ingest/data.py` | `load_instance` -> `Instance` (orders, locations, distance matrix) |
| | `src/dispatch/audit.py` | Data audit: triangle-inequality breaks, per-location profile, single-stop feasibility, one-visit checks |
| **Solver module** | `src/dispatch/route.py` | Metrics + feasibility of one route with a fixed stop order |
| | `src/dispatch/sequencing.py` | Visit order for a stop set (`nn`, `nn_2opt`, `exact`) |
| | `src/dispatch/solvers/` | `nearest_neighbor`, `clarke_wright`, `brute` (reference); each has `solve(...) -> Solution` |
| | `src/dispatch/solution.py` | `Solution`, plan CSV export, summary tables |
| **Validator** | `src/dispatch/validate.py` | Independent plan validator: re-checks all four limits and every order from the raw data |
| **Experiments** | `experiments/run_selection.py` | Choose a route-selection + sequencing method, get routes and results |
| | `experiments/run_benchmark.py` | All 40 option sets vs brute force on the 40 stored subsets |
| | `experiments/make_subsets.py` | Builds `data/benchmark_subsets_k9.csv` |
| | `experiments/audit_report.py` | Prints the data audit (`python experiments/audit_report.py`) |
| **Tests** | `tests/test_plans.py` | Solves the instance with all 8 default methods and re-validates **every route** of each plan against all four limits, each order delivered once |
| | `tests/test_validate.py` | The validator catches duplicate / missing orders, over-capacity, over-span, wrong reported numbers |
| | `tests/test_route.py`, `test_sequencing.py`, `test_data.py` | Route metrics, sequencing, data loading |
| **Documentation** | `README.md`, `runbook.md` | Setup + one-line reproduction; environment, weekly workflow, known limitations |
| | `results/benchmark.md`, `results/benchmark.csv` | Benchmark tables for every method (generated by `run_benchmark.py`; `results/` is not committed) |
| | `DATA_FINDINGS.md`, `AI_USAGE.md` | Data quirks found; log of AI-assisted work |
| **Environment** | `requirements.txt`, `pyproject.toml` | Pinned package versions (Python 3.11+) |
