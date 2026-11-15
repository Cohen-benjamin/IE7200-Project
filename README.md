# monday-dispatch (IE7200 Project)

Vehicle routing / dispatch for the IE7200 Monday instance.

## Quick start
```bash
pip install -e ".[dev]"                          # Python 3.10+, numpy, pandas, pytest
python experiments/run_selection.py              # ONE selection (settings at the top of the file)
python experiments/run_selection.py --all        # all 12 selections, about 1 minute
python experiments/run_benchmark.py              # all option sets vs brute force, about 2 minutes (also writes benchmark_workloads.csv)
```

## Changing the methods (no solver code to edit)
Open `experiments/run_selection.py` and edit the **CHOOSE HERE** block at the top, or pass flags:

| Setting | Choices | Flag |
|---|---|---|
| `SOLVER` (route selection) | `nearest_neighbor`, `clarke_wright` | `--solver` |
| `SEQUENCING` (order of a route's stops) | `nn`, `nn_2opt`, `exact` | `--sequencing` |
| `SPLIT_ORDERS` | `False` = a location's orders stay on one van, `True` = they may be split | `--split-orders` / `--no-split-orders` |
| `LAM`, `RESEQUENCE` (Clarke-Wright only) | savings shape, re-order merged routes | `--lam`, `--resequence` / `--no-resequence` |

Each run writes `results/<solver>_<sequencing>_<together|split>/routes.csv` (every route) and `summary.md`
(miles, routes, runtime, utilization, tightest limits, and a driver-workload table: drive, unload, duty and span minutes per route). **Every plan is re-checked against the raw data by the
independent validator before it is saved.** `--list` prints the 12 command lines to run one by one.
All limits (capacity, 660 / 840 / 600 minutes, unload rates, speed) are rows of
`data/csv/ie7200_Mon_parameters.csv`; edit a row and re-run to see the effect.

See `runbook.md` for the full workflow and `LADDER.md` for the measured results of every method.

## Layout
| Path | Purpose |
|---|---|
| `data/csv/` | Monday instance CSVs (`ie7200_Mon_*.csv`) |
| `src/dispatch/params.py` | `Params`, `VehicleType` dataclasses |
| `src/dispatch/data.py` | Ingestion -> `Instance` |
| `src/dispatch/audit.py` | Data property checks |
| `src/dispatch/route.py` | Metrics + feasibility for a fixed sequence |
| `src/dispatch/sequencing.py` | Feasible/cheap order for a stop set |
| `src/dispatch/solution.py` | `Solution`, reporting, export |
| `src/dispatch/validate.py` | Independent plan validator |
| `src/dispatch/solvers/` | `brute`, `nearest_neighbor`, `clarke_wright` |
| `experiments/run_selection.py` | Choose a route-selection + sequencing method, get routes and results |
| `experiments/run_benchmark.py` | Every option set vs brute force on seeded subsets |
| `tests/` | pytest suite |
