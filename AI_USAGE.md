# AI Usage Log

**Tool:** Claude Code (CLI). Sonnet 5.5 for most work; Opus 5.5 for planning stage of the project

**How I worked**
-I first worked with AI to setup the repository in Git and used it to brainstorm the structure.
- Then I chose algorithms from class and explained how they would work to AI and asked how they should be built in code
- I then let AI use plan mode to have a plan to build the code and I reviewed the plan before executing
- AI then built the code framework for that module
- I worked in small increments going module by module.
- I reviewed the code AI had written line by line asking for clarifying questions along the way and had it add comments as well as me add comments
- After each step I had AI ask me quiz questions on the new code to ensure that I had a full understanding of what was written
- Checked by running the tests and solvers, and confirming the validator passes every saved plan.
- AI also wrote the tests in tests/. They are outside the main package (src/dispatch/) and check data loading, route metrics, sequencing, the validator, and that every route of the nearest-neighbour and Clarke-Wright plans is legal on all four limits. 
- AI was used to log changes in this AI usage module to ensure I was capturing all usage of AI
- AI was used to comment the code and get clarity on why decitions were made if jn
- AI was used to review algorithm implementation and ensure there were no large gaps. 
- AI was also used to help commit the code to GIT properly

## What the AI did and what I decided

| Area | AI did | My decisions / changes |
|---|---|---|
| Setup & data (8 Nov) | Repo scaffold; `params.py`, `data.py`, `test_data.py`; environment fixes; line comments | Van-only for M1; CSV input only (no JSON provided); `vehicle_types.csv` loaded but unused in M1. Confirmed derived values (drive min/mile = 60 / speed; max span = window end − start). Total unload matches 1,324.7 only within ±0.05 (CSV sums to 1,324.65) |
| Data audit (8 Nov) | `audit.py`: triangle-inequality breaks, single-stop feasibility, one-visit checks | Audit is read-only. Caught an operator-precedence bug (depot listed as a stop). findings kept in `DATA_FINDINGS.md`(AI written human reviewed) |
| Core routing (11–13 Nov) | `route.py`, `sequencing.py` nearest neighbor first then `validate.py`, `solution.py` |removed edge cases from validate .py as I couldn’t understand the code and reasoning behind them. I also asked for a  scaffolding for the other sequencing to be added|
| Solvers (13 Nov) | Nearest neighbour, brute force, Clarke-Wright; benchmark and selection runners | Every plan is validated before saving. Order splitting in Clarke-Wright added at my request |
| Core routing (13 Nov) | `sequencing.py` added nearest neighbor 2 opt and exact solvers| 2-opt algorithm modified for understandability from the user|
| Algorithm changes (15 Nov) | span-aware 2-opt; Clarke-Wright benchmark extended to splitting and 3 merge-handling options; 40 stored 9-stop subsets (20 clustered, 20 random) | Made `exact` opt-in: 1–6 min/run and never beat `nn_2opt` (still the brute-force reference). Subsets stored in a file for exact repeatability; each benchmark run twice with identical results. Finding: splitting is neutral or harmful on the subsets |
| Review & cleanup (15–16 Nov) | Per-route workload table; validator cross-checks unload time; Clarke-Wright keeps the cheaper of joined vs re-sequenced order; removed unrequested files and tests | Kept only the tests in my specs plus `test_plans.py`. Removed code I could not defend line by line (copies kept outside the repo). "Driver schedule" interpreted as per-route workload, since the data has no clock times |
| Packaging (15 Nov) | Pinned versions; `test_plans.py` (re-validates every route, each order served once); README and runbook; fresh-clone test | Fresh clone needed no fixes; two runs identical except runtime |

## Tests changed on purpose.
- 3 tests updated for span-aware 2-opt; 1 test added.
- 1 validator test added for the unload cross-check.
- 2-opt change for understandability 
