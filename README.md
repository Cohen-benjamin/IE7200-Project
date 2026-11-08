# monday-dispatch (IE7200 Project)

Vehicle routing / dispatch for the IE7200 Monday instance.

## Layout
| Path | Purpose |
|---|---|
| `data/csv/` | Monday instance CSVs (`ie7200_Mon_*.csv`) |
| `src/dispatch/params.py` | `Params`, `VehicleType` dataclasses |
| `src/dispatch/data.py` | CSV ingestion -> `Instance` |
| `src/dispatch/audit.py` | Data property checks |
| `src/dispatch/route.py` | Metrics + feasibility for a fixed sequence |
| `src/dispatch/sequencing.py` | Feasible/cheap order for a stop set |
| `src/dispatch/solution.py` | `Solution`, reporting, export |
| `src/dispatch/validate.py` | Independent plan validator |
| `src/dispatch/solvers/` | `brute`, `nearest_neighbor`, `clarke_wright` |
| `experiments/run_benchmark.py` | Solver comparison |
| `tests/` | pytest suite |

## Quick start
```bash
pip install -e ".[dev]"
pytest
python experiments/run_benchmark.py
```

See `runbook.md` for the full workflow.
