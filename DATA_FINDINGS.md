# Data Findings

Results of `dispatch.audit` on the CSVs in `data/csv/` (Monday instance).
Reproduce with `python experiments/audit_report.py`; numbers are checked in `tests/test_data.py` and `tests/test_audit.py`.

| # | Check | Finding | Impact / handling |
|---|---|---|---|
| 1 | Load integrity | Matrix is 35x35, symmetric, zero diagonal. 43 orders, 34 stops, 10,223 ft3. `OrderCount`, `TotalVolume_ft3` and `DistanceFromDepot_mi` in `locations.csv` match values recomputed from `orders.csv` and the matrix. | None; the files are consistent. |
| 2 | Total unload time | Sum of `UnloadTime_min` is 1,324.65 min (brief quotes 1,324.7). Each order's time is rounded to 2 dp in the CSV; recomputing `max(30, 0.03 * volume)` per order gives the same 1,324.65. | Tests compare totals with a tolerance (+/-0.05), per-order values with 0.006. |
| 3 | Triangle inequality | NOT metric. 270 cases (pair i<j, shortcut k) where `d[i,j] > d[i,k] + d[k,j]`, over 154 distinct pairs. Worst: `d(25,32) = 98` mi, but 25 -> 21 -> 32 = 84 mi (14 mi / 21 min shorter). | Never assume the triangle inequality (savings, insertion, lower bounds). Direct-arc route costs are pessimistic on these legs. |
| 4 | Where violations concentrate | Most frequent "too long" endpoints: 13 (50), 7 (42), 25 (39), 29 (31), 28 (31). Most frequent shortcut points: 9 (41), 17 (35), 21 (31). | Treat legs touching 13, 25, 28, 29 with suspicion when interpreting route costs; not corrected (data is taken as given). |
| 5 | Depot legs | 14 violations have the depot as an endpoint: `DistanceFromDepot_mi` is not the shortest path for stops 1, 2, 8, 27, 28, 29 (max 8 mi over). | Depot legs are charged as given in the matrix; noted as a source of pessimism in drive time. |
| 6 | Per-location resources | Every location fits one van alone. Max stop volume 1,796 ft3 (loc 7) vs 3,200; max stop unload 90 min (loc 24, 3 orders) vs 600 span. | No stop needs to be split for volume or unload time. |
| 7 | Single-stop feasibility | All 34 stops feasible on depot -> s -> depot. Tightest: loc 14 (201 mi), round-trip drive 603 of 660 min (57 min = 38 mi slack), duty 663 of 840. Far stops bind on drive, near stops on duty, loc 7 on volume. | Problem is feasible (one van per stop is a valid, if poor, solution and an upper bound of 34 routes). Loc 14 has little room to share a route. |
| 8 | One visit per location (M1) | No duplicate locations (no 0-mile pairs, `GlobalLocationId` unique); no stop forced to split (#6, #7). | "One visit per location, all its orders together" is valid for M1. Caveat: with #3, a route could in principle save miles by passing through a stop again; the model uses direct arcs and does not exploit this. |
| 9 | Mixed vehicle eligibility (M2) | Stops 7, 12, 24 mix "Straight Truck only" and "Van OK" orders. | Ignored in M1 (Van only, per CLAUDE.md). In M2 these stops may need two visits by different vehicle types. |
