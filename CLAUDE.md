# CLAUDE.md

Guidance for Claude Code in this repo.

- Package lives in `src/dispatch/`; run tests with `pytest` from repo root.
- `route.py` evaluates a fixed sequence; `sequencing.py` chooses the order. Keep that split.
- `validate.py` must stay independent of `route.py` (no shared feasibility code).
- Every solver exposes `solve(inst: Instance) -> Solution`.
- Record data quirks in `DATA_FINDINGS.md`; log AI-assisted work in `AI_USAGE.md`.
- Don't commit generated results (`results/` is gitignored).
