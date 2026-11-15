# Next Steps and Planned Fixes

Status: **proposed, not implemented.** Nothing in this file has been built yet; the numbers below were
measured on the current code (Monday instance). Update this file as items are done.

## A. Pending changes (awaiting approval)

### A1. Comparison inside `brute.py`
**Partly superseded:** `experiments/run_benchmark.py` now compares all 18 option sets against brute force on
20 seeded subsets (results in LADDER.md section 3). A reusable library function is now optional.

Add `compare_with_heuristics(instance, stops, params=None, vehicle=None, *, split_orders=False)`
returning `Comparison(table, solutions)`. It runs brute force and each heuristic on the **same** subset
and returns one table:

| method | routes | total_miles | gap_pct vs optimum | runtime_s |
|---|---|---|---|---|
| brute (optimal) | ... | ... | 0 | ... |
| nn / nn_2opt / exact | ... | ... | ... | ... |

- Heuristics come from a small registry, so Clarke-Wright can be added with one line.
- (Optional) a `run_brute.py` script was removed; `run_benchmark.py` already compares against brute force.
- Validation of saved plans stays in the runner, so `brute.py` does not depend on `validate.py`.

### A2. Raise the `max_exact_stops` default from 8 to 9
**Note:** the benchmark passes `max_exact_stops = 9` explicitly to every solver, so its numbers do not depend on
the default; changing the default would still affect other callers.

`brute.max_stops` is already 9. The surprise came from the exact-sequencing cap of 8 inside nearest
neighbour, which blocked a 9-stop route (467 miles vs the optimal 251 on one subset). Change the default in:
`sequencing.exact_sequence`, `sequencing.best_sequence`, `solvers.nearest_neighbor.solve`.

Measured cost on the full instance (nearest neighbour + exact sequencing):

| Cap | Orders together | Orders split |
|---|---|---|
| 8 | 1,865 mi, 1.9 s | 1,837 mi, 2.5 s |
| 9 | 1,848 mi, 5.0 s | 1,839 mi, 6.9 s |

About 2.5x slower; the split plan got 2 miles worse (greedy myopia, see B2).

**Tests that must change** (they encode "the limit is 8"; expected outcomes change only because the default does):
- `tests/test_sequencing.py::test_best_sequence_exact_respects_size_limit`: use a 10-stop set for the error.
- `tests/test_sequencing.py::test_too_many_stops_for_exact`: use `inst.stops[:10]`.

Also: re-run the experiments and update the exact-sequencing nearest-neighbour rows in `LADDER.md`.

## B. Fixes for the surprises seen in the brute-force comparison

### B1. `nn_2opt` can break span (k = 8 random, seed 1: 531 miles vs optimal 303)
2-opt minimises total miles and cannot see the span limit; its cheaper order broke span at the last stop,
the stop was refused, and a second route opened. Fixes, smallest first:
1. **Make 2-opt span-aware:** rank candidate orders by span excess first, then miles.
2. **Restore the inter-stop fallback rung** (removed earlier): rescued the 12-stop span-bound route, no
   effect on sets of 9 or fewer stops.
3. **Use exact sequencing for blocks of 9 or fewer stops** (partly delivered by A2).

### B2. Greedy myopia (location 14 alone; k = 8 random, seed 4: 747 miles vs optimal 539)
A better sequencing rung cannot fix this; the construction rule must change:
1. **Farthest-first seeding:** start each route at the hardest unserved stop (e.g. the 201-mile store) and
   fill it with near stops on the way. **Correction:** this would save at most 4 miles (location 14's best
   partner saves 1-4 miles in total), so it is a low-value fix. The real gap between nearest neighbour
   (1,876) and Clarke-Wright (1,525) is entirely in how the other 33 stops are grouped.
2. **Clarke-Wright savings:** merges routes by savings, not nearest-first, so it does not strand stops.
   Also the second method M1 requires.
3. **Inter-route local search (relocate, swap):** repairs stranded stops after construction; the brief
   names it as the best return per line of code.
4. **Multi-start:** run from several starts or tie-breaks and keep the best.
5. **Metaheuristic** (simulated annealing / large neighbourhood search) on top, later.

### B3. Cap artefact
Fixed by A2. A smarter exact method for larger sets (Held-Karp with two numbers per state: total miles
and inter-stop miles) is a later option.

### B4. Larger exact cap is not uniformly better
At cap 9 the split plan was 2 miles worse than at cap 8. Reinforces that a better construction rule (B2)
matters more than better sequencing.

## C. Recommended order
1. A1 + A2 (comparison inside `brute.py`, default 9).
2. B1.1 span-aware 2-opt (small).
3. B2.1 farthest-first seeding (small).
4. ~~B2.2 Clarke-Wright (required for M1).~~ **Done:** `solvers/clarke_wright.py`, best plan 1,525 miles
   (lam = 1, re-sequenced); see LADDER.md.
5. B2.3 inter-route local search.

## D. Other open items
- `AI_USAGE.md` has no rows yet for: `route.py`, `sequencing.py`, the sequencing ladder, `validate.py`,
  `solution.py`, `nearest_neighbor.py`, `brute.py`.
- `README.md` and `runbook.md` still describe `validate` loosely (the runbook names `dispatch.validate.validate`,
  which does not exist) and have no one-line reproduction command.
- Done: `experiments/run_selection.py` (choose solver / sequencing / splitting; `--all` runs 12 selections) and
  order splitting in Clarke-Wright. README documents both.
- `outputs/` holds 18 plan CSVs (6 nearest neighbour, 12 Clarke-Wright; gitignored); `tests/test_final_plan.py` validates every
  file there, so delete stale plans before submitting.
- The hand-computed `route.py` test is still skipped, waiting for your values (depot -> 4 -> 7 -> depot,
  orders 4, 10, 3, 41).
- Nothing is committed.
