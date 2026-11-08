# Data Findings

Results of checks on the CSVs in `data/csv/`.

| # | Check | Finding | Impact / handling |
|---|---|---|---|
| 1 | Size | 43 orders, 35 locations (depot = index 0); several orders share a location | Orders are the unit; group with `Instance.orders_at` |
| 2 | Volume vs capacity | Total 10,223 ft³ vs van 3,200 ft³ = 3.19 | At least 4 vans needed; `min_vehicles=4` is non-binding |
| 3 | Straight-Truck-only orders | 10 orders (1,576 ft³) flagged `RequiresStraightTruck` | Van-only phase ignores the flag (`enforce_eligibility=False`); revisit for mixed fleet |
| 4 | Distance matrix | Symmetric; **540 triangle-inequality violations** | Don't assume shortest paths; heuristics must use matrix as given |
| 5 | Far depot legs | Farthest location 201 mi (~301 min one way at 40 mph) | One round trip ~603 min of the 660 min drive cap; far stops are tightly constrained |
