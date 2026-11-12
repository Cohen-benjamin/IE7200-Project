# Method Ladder

What each method cost (runtime, effort), what it bought (miles), and why we moved on.
All numbers are measured on the Monday instance; reproduce with the command under each table.

## 1. Sequencing a fixed stop set (`dispatch.sequencing`)

**Setup.** For k = 5..9 stops, test sets are each stop plus its k-1 nearest stops
(deduplicated, 20-22 sets per k). `exact_sequence` proves the best feasible order, so heuristic
error is measured exactly. Gap = extra total miles vs exact, on sets where both found a feasible order.
"False rejection" = a set with a legal order that the method reported infeasible.

Reproduce: `python experiments/sequencing_ladder.py` (about 30 s).

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

_Pending: nearest neighbour, Clarke-Wright, brute force._
