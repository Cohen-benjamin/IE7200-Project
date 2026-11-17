# Live Demo Script (4:00)

**Plan shown:** Clarke-Wright + span-aware 2-opt re-sequencing, orders kept together, lam = 1.0
**Result (verified 2026-11-17):** 5 routes, **1,525 mi**, VALID, ~0.2 s

---

## Before you hit record

| Item | Action |
|---|---|
| Terminal | Repo root, venv active, font large (≥18 pt) |
| Warm-up | Run the demo command once so imports are cached |
| Editor tabs (in order) | `route.py`, `sequencing.py`, `solvers/clarke_wright.py`, `validate.py` |
| Fallback | Keep `results/clarke_wright_nn_2opt_together/summary.md` open in a hidden tab in case the live run fails |
| Clear | `results/` from earlier runs is fine (gitignored); the run overwrites its own folder |

Demo command (copy exactly):

```bash
python experiments/run_selection.py --solver clarke_wright --sequencing nn_2opt --no-split-orders --lam 1 --resequence
```

---

## Script

Bold = say it. *Italic* = on-screen action. Target ~130 words/min.

### 0:00–0:20 Problem (20 s)

*Show README title or a blank terminal.*

**"Monday's dispatch has 43 orders at 34 locations, served from one depot by a fleet of identical vans. A route
has to pass four limits: van volume, 660 minutes of driving, 840 minutes of duty, and a 600-minute delivery
span. The goal is the fewest total miles. I'll show how the code is built, why, and then run the best plan."**

### 0:20–0:50 Data first (30 s)

*Open `DATA_FINDINGS.md`, point at rows 3 and 7.*

**"Before solving I audited the data. Two findings drove the design. First, the distance matrix is not
metric: 270 triangle-inequality breaks. So no shortcut formulas anywhere. Every route is costed leg by
leg, straight from the matrix. Second, every stop fits one van alone, so the problem is feasible.
Location 14 is so far out that it leaves only 57 minutes of drive slack. Remember that one."**

### 0:50–1:30 Architecture: one judge, one auditor (40 s)

*Open `route.py` and scroll to `route_metrics` (line 117), then the `span_min` line.*

**"The code has four layers. `route.py` measures one route with a fixed visit order. It's the only place
the feasibility rules live. Note the span: inter-stop driving plus unload, with depot legs excluded. So the
same stops in a different order can pass or fail."**

*Switch to `sequencing.py` and show the module docstring "method ladder".*

**"`sequencing.py` chooses the order, and it always asks `route.py` for the verdict. The solvers choose
which stops share a van. Then `validate.py`"** *(open it and show the docstring)* **"re-checks every
finished plan from the raw CSVs and never imports `route.py`. For a bad plan to get through, I'd have to
make the same bug twice."**

### 1:30–2:20 The algorithm (50 s)

*Open `clarke_wright.py`, show the savings formula in `savings()` (line 71).*

**"Route building is Clarke-Wright. Start with one van per stop. The saving for joining i and j is the
two depot trips minus the link between them. Pairs are processed biggest saving first."**

*Scroll to the main loop and point at Rules 1–4.*

**"A merge has to pass four rules: different routes, both stops at route ends, feasible on all four
limits, and real miles must go down. That last rule matters on a non-metric matrix, because a positive
saving on paper doesn't guarantee real miles saved."**

*Switch to `sequencing.py` and show `cost()` inside `_nn_2opt_tour` (line 238).*

**"After each merge I re-order the stops with 2-opt. The cost is a tuple: span excess first, miles second.
So 2-opt removes span violations before it saves a single mile, and it can never turn a legal route into
an illegal one."**

### 2:20–3:10 Live run (50 s)

*Paste the demo command. Run it.*

**"This runs the selection, saves the routes, and validates them before anything is kept."**

*Output line: `5 routes, 1525 miles, 0.2 s, VALID`. Open `results/clarke_wright_nn_2opt_together/summary.md`.*

**"Five routes, 1,525 miles, in a fifth of a second. The validator passed: every order delivered once, all
four limits met. Look at route 4. That's location 14 alone: 603 of 660 drive minutes, the same number the
audit predicted. The tightest limits are duty on route 5, with 12.6 minutes left, and span on route 3,
with 13.5. These routes are full, not padded."**

### 3:10–3:45 Evidence it's good (35 s)

*Show `results/benchmark.md`, gap table.*

**"For 34 stops I can't prove optimality, so I benchmarked against brute force on 40 stored 9-stop
subsets, where the optimum is known. This method averages 0.25% above optimal and hits the exact optimum
on 31 of 40. On the full instance, greedy nearest neighbour needs six vans and 1,876 miles. Exact
sequencing gives the same 1,525 miles but takes 50 seconds instead of 0.2."**

### 3:45–4:00 Limits and close (15 s)

**"Limitations: this is Milestone 1, so vans only, with no straight-truck rule and no dock waves. And there's
no optimality proof at full size. Every plan is reproducible from one command and checked by an
independent validator. Thanks."**

---

## Numbers to have memorized

| Fact | Value | Source |
|---|---|---|
| Orders / locations / volume | 43 / 34 / 10,223 ft3 | DATA_FINDINGS #1 |
| Triangle violations | 270 | DATA_FINDINGS #3 |
| Best plan | 5 routes, 1,525 mi, 0.2 s | run_selection |
| Savings pairs → merges | 561 pairs → 29 merges (374 not endpoint, 81 same route, 77 infeasible, 0 no-gain) | `stats=` arg |
| Gap vs brute force (40 subsets) | mean 0.25%, max 2.61%, optimal 31/40 | benchmark.md |
| Nearest neighbour (best variant) | 6 routes, 1,876 mi | benchmark.md |
| Exact sequencing | 1,525 mi, ~50 s | run_selection `--sequencing exact` |
| Tests | 78 passed | pytest |

## Likely follow-up questions (have an answer ready)

1. **Why lam = 1.0 when lam = 1.2 has a lower subset gap (0.21% vs 0.25%)?** On the real 34-stop
   instance lam = 1.2 gives 6 routes / 1,535 mi vs 5 / 1,525. The decision metric is the full instance;
   subsets are a sanity check on quality, not the target.
2. **Why does 2-opt use a tuple cost and not a penalty weight?** A tuple compares lexicographically, so
   there's no weight to tune and no hard-coded constant. Span excess is always reduced before miles.
3. **Why is rule 4 needed if saving > 0?** With lam ≠ 1 the saving is only a ranking score, and after
   re-sequencing the merged miles aren't the formula's miles. Checking real miles keeps the plan from
   ever getting longer. (0 rejections on this run, but it's a guard.)
4. **Why "not endpoint" rejects 374 pairs:** an interior stop has no depot leg to remove. Joining there would
   cut its route in two.
5. **Why can't you just validate with `route.py`?** Then a bug in `route.py` would pass its own check.
   The validator is a second, independent implementation by design (CLAUDE.md rule).
