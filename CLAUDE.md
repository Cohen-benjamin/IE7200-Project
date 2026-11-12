# CLAUDE.md

Guidance for Claude Code in this repo.

- Package lives in `src/dispatch/`; install with `pip install -e .` from repo root.
- `route.py` evaluates a fixed sequence; `sequencing.py` chooses the order. Keep that split.
- `validate.py` must stay independent of `route.py` (no shared feasibility code).
- Every solver exposes `solve(inst: Instance) -> Solution`.
- Record data quirks in `DATA_FINDINGS.md`; log AI-assisted work in `AI_USAGE.md`.
- Don't commit generated results (`results/` is gitignored).


## My goal
I must explain and defend every line in written/recorded follow-ups.
Optimise for my understanding, not speed.

## Rules for you
- Before writing code, propose a design (functions, signatures, data flow) and wait for my approval.
- One module or function group per task. Small diffs. Do not touch files I didn't name.
- No new dependencies without asking. Allowed: numpy, pandas, pytest, matplotlib.
- Every function: docstring with inputs, outputs, units (miles, minutes, ft3).
- No hard-coded constants. All parameters come from the Params object.
- After implementing, give me: (1) a 5-line summary, (2) the one line most likely to hide a bug, (3) 3 quiz questions about the code.
- Never "fix" a failing test by changing the test without telling me why.

## Domain facts
- Unit of coverage = ORDER (43). Stop = location visit (34 locations). One stop may discharge several orders; unload time is paid per order.
- Distance matrix is symmetric but NOT metric. Never assume triangle inequality.
- Route feasibility = ALL of: volume <= cap; drive (1.5 min/mi, incl. depot legs) <= 660; drive + unload <= 840; span (inter-stop drive + all unload) <= 600.
- Span depends on SEQUENCE. A stop set is feasible if ANY ordering passes.
- M1 = homogeneous Van fleet only. Ignore RequiresStraightTruck and dock waves (M2), but keep vehicle type as a parameter.