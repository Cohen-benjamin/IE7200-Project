# Runbook

1. The Monday instance is the five CSVs in `data/csv/` (no JSON source).
2. Install: `pip install -e ".[dev]"`
3. Audit data: run `dispatch.audit.audit` on the loaded instance; record findings in `DATA_FINDINGS.md`.
4. Run tests: `pytest`
5. Benchmark solvers: `python experiments/run_benchmark.py`
6. Validate every exported plan with `dispatch.validate.validate` before reporting.
