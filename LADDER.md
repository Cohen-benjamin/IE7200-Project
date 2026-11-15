# Method Ladder

What each method cost (runtime, effort), what it bought (miles), and why we moved on.
All numbers are measured on the Monday instance; reproduce with the command under each table.

## 1. Sequencing a fixed stop set (`dispatch.sequencing`)

**Setup.** For k = 5..9 stops, test sets are each stop plus its k-1 nearest stops
(deduplicated, 20-22 sets per k). `exact_sequence` proves the best feasible order, so heuristic
error is measured exactly. Gap = extra total miles vs exact, on sets where both found a feasible order.
"False rejection" = a set with a legal order that the method reported infeasible.

Measured once with the sequencing functions in `src/dispatch/sequencing.py` (the one-off script was removed; the final tools are `run_selection.py` and `run_benchmark.py`).

| k | Method | Legal sets | Found | False rejections | Mean gap | Max gap | Mean time | route_metrics calls | Orders scored |
|---|---|---|---|---|---|---|---|---|---|
| 5 | nn | 20 | 100% | 0 | 3.52% | 20.83% | 0.7 ms | 1.0 | 1 |
| 5 | nn_2opt | 20 | 100% | 0 | 0.60% | 6.25% | 0.7 ms | 1.0 | 17 |
| 5 | exact | 20 | 100% | 0 | 0 | 0 | 1.1 ms | 1.14 | 60 |
| 6 | nn | 20 | 95.0% | 1 | 3.19% | 19.05% | 0.7 ms | 1.0 | 1 |
| 6 | nn_2opt | 20 | 100% | 0 | 0.58% | 5.32% | 0.8 ms | 1.0 | 27 |
| 6 | exact | 20 | 100% | 0 | 0 | 0 | 2.7 ms | 1.14 | 360 |
| 7 | nn | 19 | 94.7% | 1 | 3.88% | 27.84% | 0.6 ms | 1.0 | 1 |
| 7 | nn_2opt | 19 | 100% | 0 | 0.55% | 6.60% | 0.7 ms | 1.0 | 39 |
| 7 | exact | 19 | 100% | 0 | 0 | 0 | 18.6 ms | 1.59 | 2,520 |
| 8 | nn | 15 | 93.3% | 1 | 5.13% | 28.87% | 0.9 ms | 1.0 | 1 |
| 8 | nn_2opt | 15 | 100% | 0 | 0.50% | 5.61% | 0.9 ms | 1.0 | 58 |
| 8 | exact | 15 | 100% | 0 | 0 | 0 | 146 ms | 2.05 | 20,160 |
| 9 | nn | 8 | 100% | 0 | 6.61% | 28.00% | 1.2 ms | 1.0 | 1 |
| 9 | nn_2opt | 8 | 100% | 0 | 0.93% | 5.61% | 1.4 ms | 1.0 | 76 |
| 9 | exact | 8 | 100% | 0 | 0 | 0 | 1,521 ms | 2.55 | 181,440 |

**Span-bound long route** (12 stops `[25,1,2,12,11,9,8,5,10,6,4,3]`, too large for exact).
The order as listed is legal (span 594 of 600), but:

| Method | Feasible | Miles | Span (limit 600) |
|---|---|---|---|
| nn | no | 218 | 610.5 |
| nn_2opt | no | 195 | 675.0 |

### Rungs

| Rung | Idea | Complexity | What it bought | Why we moved on |
|---|---|---|---|---|
| 0 nn | Go to the nearest unvisited stop | O(n^2) | Fast baseline, 3.2-6.6% above optimal on average, up to 29% | Large worst-case gap; 1 false rejection at k = 6, 7, 8 |
| 1 nn_2opt | Reverse segments while total miles drop | O(n^3) per pass | Mean gap cut to 0.5-0.9%, max ~6%; no false rejections on k <= 9 sets | Minimises total miles only, so it can lengthen inter-stop miles and break span (12-stop route: 675 min) |
| exact | Every order, dominance pruning | O(k * k!) | Proven optimum or proven infeasible | Too slow beyond ~9 stops: 1.5 s at 9, x~k per extra stop |

### Findings
- 2-opt is the best return per line of code: it removes about 85% of nearest neighbour's mileage gap.
- Exact needs only 1-3 `route_metrics` calls per set (dominance pruning); its cost is scoring all
  k!/2 orders.
- **Known limitation:** both heuristic rungs optimise total miles only. On span-bound sets larger than
  the exact limit they can reject a legal route (the 12-stop route above), which is the trap the brief
  warns about in section 4.2. An inter-stop fallback rung was built and measured (it rescued this
  route, and matched rung 1 on every k <= 9 set) but was removed by design choice to keep the ladder
  to two heuristic rungs plus exact.
- Limits of this test: near-neighbour sets only, k <= 9. Heuristic quality on 10-12 stop routes is not
  measured exactly (exact is too slow there).

## 2. Plan-level solvers

### Rung 0: nearest neighbour (`dispatch.solvers.nearest_neighbor`)

From the current position, go to the nearest location whose orders still fit (all four limits,
checked by sequencing the tentative route); close the route when nothing fits.
Tie-break: nearest from the last location added; equal distance -> lower LocationIndex.

Reproduce: `python experiments/run_selection.py --solver nearest_neighbor ...` (see `--list`). Every plan below was saved to CSV and
re-checked by `validate_plan` (0 violations each).

| Sequencing | Orders per location | Routes | Total miles | Runtime | Min drive slack | Min span slack |
|---|---|---|---|---|---|---|
| nn | together | 6 | 1,876 | 0.06 s | 57 min | 80.2 min |
| nn | split allowed | 6 | 1,919 | 0.09 s | 57 | 46.5 |
| nn_2opt | together | 6 | 1,888 | 0.08 s | 57 | 51.6 |
| nn_2opt | split allowed | 6 | 1,886 | 0.18 s | 57 | 45.0 |
| exact | together | 6 | 1,865 | 2.05 s | 57 | 40.5 |
| exact | split allowed | 6 | **1,837** | 2.74 s | 57 | 40.5 |

**Default run (nn, together): 6 routes, 1,876 miles.**

| Route | Stops | Miles | Volume | Drive | Span |
|---|---|---|---|---|---|
| 1 | 3-12-11-9-6-4-5-10-8-2-1 | 142 | 61.7% | 32.3% | 86.3% |
| 2 | 7-25-26-17-16-22-21-20-23 | 261 | 95.8% | 59.3% | 86.6% |
| 3 | 13-24-18-19 | 381 | 34.7% | 86.6% | 78.8% |
| 4 | 15-30-29-27-28 | 313 | 98.2% | 71.1% | 60.1% |
| 5 | 31-32-33-34 | 377 | 19.1% | 85.7% | 34.0% |
| 6 | 14 | 402 | 10.2% | 91.4% | 10.0% |

### Findings
- **Where nearest neighbour is myopic: the 201-mile store (location 14).** Its only possible
  partners are near-depot stops 3, 4, 5, 6, 7 and 10 (any other stop pushes driving over 660 min).
  NN spends them first: route 1 takes 3, 4, 5, 6, 10 and route 2 takes 7, so by the time it
  reaches location 14 nothing is left and it drives 402 miles alone for 325 ft3 (10% full, 91% of
  the drive limit). NN never saves a partner for a hard stop. This is the same in all six runs.
  **Correction (measured later, see Clarke-Wright below):** this costs very little. Pairing location 14
  with its best feasible partner (stop 3) saves only 4 miles, and the others save 1-3, out of 1,876.
  Clarke-Wright also leaves location 14 alone in its best plan. The 201-mile store is not where
  nearest neighbour loses; see the Clarke-Wright findings.
- **Far stops are drive-bound, not volume-bound.** Routes 3, 5 and 6 are 10-35% full by volume but
  86-91% of the drive limit. The plan's average volume utilization is 10,223 / (6 x 3,200) = **53%**,
  below the 60% the brief says the client's manual dispatching achieves, so this baseline does not
  yet beat the client on that measure.
- **Better sequencing helps, a little.** Exact sequencing is about 2% shorter than plain nn
  (1,837 vs 1,876 miles) but about 35x slower (2.7 s vs 0.06 s). Splitting orders only paid off
  with exact sequencing (-28 miles); with nn it was worse (+43). One instance and one
  deterministic run per option, so these small differences are indicative, not statistically tested.
- **Known limitations:** no optimality gap is available yet (minimum vans by volume alone is 4;
  NN uses 6). A route's stops are only as well ordered as the sequencing method used, and nn / nn_2opt
  can wrongly refuse a legal span-bound route (see section 1).

### Reference: brute force on 6-9 stops (`dispatch.solvers.brute`)

Every set partition of the subset's stops is a candidate plan; each block (group of stops) is
sequenced exactly once, and the cheapest feasible partition wins. Number of partitions = Bell number:
B(6) = 203, B(7) = 877, B(8) = 4,140, B(9) = 21,147, B(12) = 4.2 million, B(34) ~ 2.1 x 10^28.
There are only 2^n - 1 blocks (511 at n = 9), so the cost is dominated by sequencing the biggest blocks.
Measured: 6 stops 0.05 s, 7 stops 0.12 s, 8 stops 0.5 s, 9 stops 3.5-3.8 s.
Scope: optimal among plans that keep each location's orders on one van.

**How far from optimal is nearest neighbour?** 5 seeded subsets per row; random = k stops drawn at random,
clustered = a stop plus its k-1 nearest. Exact sequencing in NN was given `max_exact_stops = k`.
All 40 brute plans were saved and re-checked with `validate_plan` against the subset's problem (0 violations).
Reproduce: `python experiments/run_benchmark.py` (brute-force subsets; about 2 minutes).

| k | Subsets | Sets needing 2 routes | nn mean gap | nn_2opt mean gap | exact mean gap | Brute time |
|---|---|---|---|---|---|---|
| 6 | random | 3 of 5 | 33.8% | 26.6% | 30.8% | 0.05 s |
| 6 | clustered | 0 of 5 | 3.0% | 0.0% | 0.0% | 0.04 s |
| 7 | random | 4 of 5 | 26.8% | 24.7% | 24.9% | 0.12 s |
| 7 | clustered | 0 of 5 | 3.6% | 0.5% | 0.0% | 0.11 s |
| 8 | random | 4 of 5 | 13.9% | 33.2% | 19.9% | 0.51 s |
| 8 | clustered | 0 of 5 | 1.9% | 0.1% | 0.0% | 0.45 s |
| 9 | random | 4 of 5 | 22.6% | 31.8% | 19.4% | 3.81 s |
| 9 | clustered | 2 of 5 | 5.4% | 3.9% | 3.9% | 3.50 s |

### Findings
- **Where nearest neighbour loses badly: groups of stops spread far apart.** On random subsets the
  optimum often needs two routes, and NN's grouping can cost 40-66% more miles (mean gaps 14-34%).
  On tight clusters one route usually suffices and 2-opt / exact sequencing is optimal in 20 of 25 cases.
- **A better sequencing rung is not always better inside a greedy solver.** Two measured cases
  (k = 8 random): (1) seed 1, `nn_2opt` found an order with fewer total miles that breaks span at the last
  stop, refused stop 30, and opened a second route: 531 miles against the optimal 303 (the span trap from
  section 1, now costing a whole route). (2) seed 4, exact sequencing found legal orders that `nn` missed,
  packed six stops on route 1, and stranded stops 24 and 34: 747 miles against the optimal 539.
  Letting a route absorb more stops early is not the same as a good plan: this is greedy myopia.
- **Read the table with care:** 23 of the 40 subsets are single-route, where brute force is trivially one
  route. Five seeds per row and one deterministic NN run per option, so the means are indicative, not
  statistically tested, and subsets are not the full 34-stop instance.

### Rung 1: Clarke-Wright savings, parallel (`dispatch.solvers.clarke_wright`)

Start with one route per location; join route ends in order of saving
s_ij = d(0,i) + d(0,j) - lam * d(i,j). A merge needs: (1) different routes, (2) both stops are route
endpoints, (3) the merged route passes all four limits, (4) real miles drop. `resequence=True` re-orders
the merged stop set with `nn_2opt` instead of keeping the end-to-end order.

Reproduce: `python experiments/run_selection.py --solver clarke_wright ...` (see `--list`). All 12 plans below were saved and re-checked
by `validate_plan` (0 violations).

**Negative savings** (561 stop pairs; the matrix is not metric): lam 0.5 and 0.8: 0 | lam 1.0: **1**
(stops 13 and 28: 71 + 121 - 194 = -2 mi) | lam 1.2: 83 | lam 1.5: 260 | lam 2.0: 303.

| lam | Re-sequence | Routes | Total miles | Runtime | Min drive slack | Min span slack |
|---|---|---|---|---|---|---|
| 0.5 | no | 6 | 1,682 | 0.21 s | 4.5 min | 3.0 min |
| 0.5 | yes | 5 | 1,583 | 0.18 s | 1.5 | 4.5 |
| 0.8 | no | 5 | 1,601 | 0.15 s | 4.5 | 0.7 |
| 0.8 | yes | 5 | 1,585 | 0.17 s | 3.0 | 3.0 |
| 1.0 | no | 5 | 1,546 | 0.10 s | 57.0 | 7.5 |
| **1.0** | **yes** | **5** | **1,525** | 0.20 s | 57.0 | 13.5 |
| 1.2 | no | 6 | 1,539 | 0.10 s | 57.0 | 39.0 |
| 1.2 | yes | 6 | 1,535 | 0.17 s | 57.0 | 15.0 |
| 1.5 | no | 6 | 1,562 | 0.08 s | 57.0 | 46.5 |
| 1.5 | yes | 6 | 1,546 | 0.14 s | 57.0 | 15.0 |
| 2.0 | no | 6 | 1,635 | 0.15 s | 55.5 | 73.5 |
| 2.0 | yes | 6 | 1,644 | 0.14 s | 57.0 | 105.0 |

**Best: lam = 1.0, re-sequenced: 5 routes, 1,525 miles** (nearest neighbour: 6 routes, 1,876; its best
option, exact sequencing with splitting, 1,837 at cap 8). Routes: 8, 7, 11, 1 and 7 stops; volume
utilization 64%, 93%, 71%, 10%, 82% (average 10,223 / (5 x 3,200) = 64%, above the 60% the brief quotes for
manual dispatching). Tightest limits: duty 12.6 min on route 5, span 13.5 min on route 3.

Merge decisions at lam = 1, no re-sequencing (561 pairs): 29 merged, 77 same route, 365 not endpoints,
90 infeasible, 0 no real-mile gain.

### Findings
- **Clarke-Wright beats nearest neighbour by 18.7%** (1,525 vs 1,876 miles) with one fewer van, in 0.2 s.
- **Location 14 is not the difference.** Both plans keep it alone at 402 miles, so the whole 351-mile gap
  comes from how the other 33 stops are grouped. Pairing location 14 with its best partner would save only
  1-4 miles (stop 3: 4 miles). Setting lam = 0.5 does pair it (with 4, 10, 6, 5) but the total gets worse
  (1,583 / 1,682).
- **lam matters, and 1.0 is best here.** Miles rise on both sides (lam 0.5: 1,583-1,682; lam 2.0:
  1,635-1,644). The ranking is only a heuristic; the textbook formula was the best single setting tested.
- **The "real miles must drop" rule never fired** (0 rejections for no gain, at every lam). Even at lam = 1.5,
  where 260 shaped savings are negative, every merge that passed the other three conditions also saved
  real miles: joining two route ends removes two depot legs, which are long. The rule is a safeguard here,
  not an active filter. Most pairs (about 65%) are rejected for not being endpoints.
- **Re-sequencing helps a little** (0-21 miles) at lam <= 1.5 and hurts slightly at lam = 2.0 (1,644 vs 1,635).
  It is inside a greedy method, so a better order for a merged route can change later merges.
- **Known limitations:** one instance and no optimality gap yet (brute force only reaches 9 stops;
  minimum vans by volume is 4, plan uses 5). `nn_2opt` re-sequencing can wrongly refuse a legal span-bound
  merge (section 1). The solver starts from one route per location, so it never splits a location's orders.

## 3. Benchmark: every option set together (`experiments/run_benchmark.py`)

One command: `python experiments/run_benchmark.py` (about 1 min 45 s). Writes `results/benchmark.csv` and
`results/benchmark.md` (gitignored). Every one of the 398 plans was saved to CSV and passed `validate_plan`
before being recorded. Settings fixed in the script: subsets of 8 and 9 stops, random and clustered, seeds 0-4
(20 subsets); `max_exact_stops = 9` for every solver. Gap = extra miles vs brute force on the same subset.

**Full instance (34 stops, 43 orders; no optimum known, so no gap):**

| Method | Routes | Total miles | Avg / max volume util | Tightest span slack | Tightest drive slack | Runtime |
|---|---|---|---|---|---|---|
| clarke_wright[lam=1.0, reseq, nn_2opt] | 5 | **1,525** | 64% / 93% | 13.5 min | 57.0 min | 0.25 s |
| clarke_wright[lam=1.2, reseq, nn_2opt] | 6 | 1,535 | 53% / 97% | 15.0 | 57.0 | 0.17 s |
| clarke_wright[lam=1.0, as-is] | 5 | 1,546 | 64% / 99% | 7.5 | 57.0 | 0.11 s |
| nearest_neighbor[exact, split] | 6 | 1,839 | 53% / 94% | 56.1 | 57.0 | 9.6 s |
| nearest_neighbor[exact, together] | 6 | 1,848 | 53% / 96% | 66.7 | 57.0 | 5.5 s |
| nearest_neighbor[nn, together] | 6 | 1,876 | 53% / 98% | 80.2 | 57.0 | 0.08 s |

(Full table of all 18 option sets: `results/benchmark.md`.)

**Seeded subsets (20), selected rows, sorted by mean gap:**

| Method | Mean gap | Max gap | Optimal | Mean runtime |
|---|---|---|---|---|
| brute force (reference) | 0.00% | 0.00% | 20/20 | 2.15 s |
| clarke_wright[lam=1.2, as-is] | 0.47% | 2.89% | 10/20 | 0.011 s |
| clarke_wright[lam=1.0, reseq, nn_2opt] | 1.21% | 11.22% | 15/20 | 0.011 s |
| clarke_wright[lam=1.0, as-is] | 1.28% | 11.22% | 12/20 | 0.009 s |
| clarke_wright[lam=0.5, as-is] (worst CW) | 4.55% | 14.19% | 2/20 | 0.011 s |
| nearest_neighbor[exact, together] (best NN) | 10.80% | 56.78% | 12/20 | 0.68 s |
| nearest_neighbor[nn, together] | 10.94% | 57.01% | 5/20 | 0.006 s |
| nearest_neighbor[nn_2opt, together] | 17.23% | 75.25% | 8/20 | 0.007 s |
| nearest_neighbor[nn_2opt, split] (worst NN) | 18.22% | 83.83% | 8/20 | 0.008 s |

### Findings
- **Every Clarke-Wright option set beats every nearest-neighbour option set on the subsets**: the worst
  Clarke-Wright mean gap (4.55%) is smaller than the best nearest-neighbour mean gap (10.79%).
- **On the full instance** the best Clarke-Wright plan is 17.1% shorter than the best nearest-neighbour plan
  (1,525 vs 1,839 miles), uses one fewer van, and has higher average volume utilization (64% vs 53%).
- **No single lam wins everywhere.** lam = 1.2 without re-sequencing has the lowest mean gap on subsets (0.47%);
  lam = 1.0 with re-sequencing is best on the full instance (1,525 vs 1,539). With only 20 subsets this is
  indicative, not a tuned result.
- **`nn_2opt` is worse than plain `nn` on subsets** (17.2% vs 10.9% mean gap): minimising total miles can break
  span and refuse a legal route (section 1).
- **No option set ever beat brute force** (no negative gaps), including the split-orders ones.
- **Limits:** 10 of the 20 subsets fit on one route, where brute force is trivial; subsets are not the full
  instance; there is still no optimality gap for the 34-stop plan (brute force stops at 9 stops).

## 4. All selections on the full instance (`experiments/run_selection.py --all`)

Every combination of route selection x sequencing x orders together/split, lam = 1.0, Clarke-Wright
re-sequencing on, exact cap 9. All 12 plans passed `validate_plan` (about 1 minute in total). Each plan's
routes and summary are in `results/<solver>_<sequencing>_<together|split>/`; the ranking is in
`results/all_selections.md`.

| Rank | Solver | Sequencing | Orders | Routes | Miles | Runtime |
|---|---|---|---|---|---|---|
| 1 | clarke_wright | nn_2opt | together | 5 | **1,525** | 0.2 s |
| 2 | clarke_wright | nn_2opt | split | 5 | 1,525 | 0.3 s |
| 3 | clarke_wright | exact | together | 6 | 1,538 | 21.4 s |
| 4 | clarke_wright | exact | split | 6 | 1,563 | 19.6 s |
| 5 | clarke_wright | nn | together | 5 | 1,578 | 0.1 s |
| 6 | clarke_wright | nn | split | 5 | 1,578 | 0.1 s |
| 7 | nearest_neighbor | exact | split | 6 | 1,839 | 9.2 s |
| 8 | nearest_neighbor | exact | together | 6 | 1,848 | 5.7 s |
| 9 | nearest_neighbor | nn | together | 6 | 1,876 | 0.1 s |
| 10 | nearest_neighbor | nn_2opt | split | 6 | 1,886 | 0.1 s |
| 11 | nearest_neighbor | nn_2opt | together | 6 | 1,888 | 0.1 s |
| 12 | nearest_neighbor | nn | split | 6 | 1,919 | 0.1 s |

### Findings
- **Clarke-Wright now has an order-splitting option** (nodes are single orders; orders at one location are
  0 miles apart, so they merge first). With splitting off its results are unchanged: a regression test pins
  all 12 earlier plans (lam x re-sequence) to their recorded miles.
- **Splitting changed nothing for Clarke-Wright on this instance with `nn` or `nn_2opt` sequencing** (identical
  miles), **and made it worse with exact sequencing** (1,563 vs 1,538). No location actually needed splitting
  (audit finding #8), so splitting is an extra choice the greedy merges can use badly.
- **For nearest neighbour, splitting only helped with exact sequencing** (1,839 vs 1,848), and hurt with `nn`
  (1,919 vs 1,876), as in section 2.
- **More careful sequencing is not always better inside a greedy method:** Clarke-Wright with `exact` (1,538)
  is worse than with `nn_2opt` (1,525), and `nn` is worst (1,578). Exact sequencing is also about 100x slower.
- **A route sitting exactly on a limit:** Clarke-Wright with `nn` sequencing has a route with 0.0 minutes of
  span slack. It is legal under the strict rule (slack >= 0) but has no margin.
- Same caveats as before: one instance, deterministic runs, no optimality gap for 34 stops.
