# Runbook

1. Place `ie7200_Mon.json` in `data/` (and CSVs in `data/csv/`).
2. Install: `pip install -e ".[dev]"`
3. Audit data: run `dispatch.audit.audit` on the loaded instance; record findings in `DATA_FINDINGS.md`.
4. Run tests: `pytest`
5. Benchmark solvers: `python experiments/run_benchmark.py`
6. Validate every exported plan with `dispatch.validate.validate` before reporting.
