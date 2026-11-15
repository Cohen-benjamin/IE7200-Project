"""Clarke-Wright savings heuristic, parallel version (rung 1 of the solver ladder).

How it works
------------
Start with one route per NODE (depot -> node -> depot). A node is a location
when orders stay together, or a single order when split_orders=True (below).
Joining two routes end to end removes one trip back to the depot and one trip
out again, which saves miles. For nodes i and j the "saving" is
    s_ij = d(0,i) + d(0,j) - lam * d(i,j)
(d = miles, 0 = depot, lam = a shape parameter; lam = 1 is the textbook
formula and equals the TRUE miles saved by joining route-end i to route-start j).
Go through all pairs, biggest saving first, and merge when the rules below allow.
"Parallel" means every route exists at the same time and any pair may merge
(the "sequential" version grows one route at a time instead).

Negative savings (this matrix is NOT metric)
--------------------------------------------
If the triangle inequality held, d(i,j) <= d(0,i) + d(0,j) and no saving would
be negative. On this instance, over the 561 stop pairs (orders together):
    lam = 0.5: 0 negative   lam = 1.0: 1 negative (stops 13 and 28:
    71 + 121 - 194 = -2)    lam = 1.5: 260 negative   lam = 2.0: 303 negative
At lam = 1 a negative saving means the join would ADD miles, so it must be
skipped. For other lam a saving is only a ranking score, and a negative score
can still save real miles. So the skip rule is on REAL miles: a merge is
accepted only if the merged route is shorter than the two routes it replaces.
(At lam = 1 without re-sequencing this is exactly "skip negative savings".)

The four merge conditions, for a pair (i, j) taken in savings order
---------------------------------------------------------------------
1. i and j are on DIFFERENT routes. Joining a route to itself would close a
   loop that never returns to the depot.
2. i and j are both route ENDPOINTS (first or last node). An endpoint is the
   node next to the depot, so its depot leg is the one the merge removes. An
   interior node has no depot leg to remove, and joining there would have to
   cut a route in two.
3. The merged route is FEASIBLE on all four limits (volume, drive, duty,
   span), decided by route.py on the joined order, or - with resequence=True -
   by sequencing.py on the merged stop SET in its best order. A merge that
   would visit a location twice (not back to back) also fails here.
4. REAL miles drop: merged miles < miles of route A + miles of route B.
Each rejected pair is counted by reason (see the `stats` argument).

What "split orders" means here
------------------------------
- split_orders=False (default): the nodes are LOCATIONS. All orders at a
  location always travel together, so each location is visited by one van.
- split_orders=True: the nodes are ORDERS (43 on Monday). Two orders at the
  same location are 0 miles apart, so their saving is the largest possible
  (2 x d(0, location)) and they merge first; they end up on different vans
  only when a limit forces it. Every order is still delivered exactly once.
If a node does not fit one van alone, solve raises a clear error naming it.

Units: miles, minutes, ft3.
"""
from __future__ import annotations

import dataclasses
import itertools
import time

from dispatch.data import Instance
from dispatch.params import Params, VehicleType
from dispatch.route import route_metrics
from dispatch.sequencing import METHODS, best_sequence
from dispatch.solution import Solution, make_solution

# Vehicle used when none is given (M1 fleet). A name, not a model number.
DEFAULT_VEHICLE = "Van"


def savings(instance: Instance, nodes, lam: float = 1.0,
            location_of: dict | None = None) -> list[tuple[float, int, int]]:
    """The savings s_ij = d(0,i) + d(0,j) - lam * d(i,j) for every pair of nodes.

    Inputs:
        instance: problem instance (distance matrix in miles).
        nodes: ids to pair up (depot excluded): locations, or order ids.
        lam: shape parameter; 1.0 is the textbook formula.
        location_of: node id -> LocationIndex. Omit when the nodes ARE
            locations; pass it when the nodes are orders.
    Output:
        list of (saving, i, j) with i < j, biggest saving first; equal
        savings are ordered by (i, j), so the result is deterministic.
        Savings can be negative because the matrix is not metric.
    """
    d = instance.dist_mi                                     # miles between any two locations
    depot = instance.depot_index                             # row/column of the depot (0)
    loc = location_of or {n: n for n in nodes}               # a node's location (itself, if it is one)
    out = []                                                 # will hold (saving, i, j) tuples
    # combinations(..., 2) gives every unordered pair once: (1,2), (1,3) ... (not (2,1) as well).
    # Once is enough because the matrix is symmetric: d[i,j] == d[j,i].
    # Every pair of nodes once (i < j); the saving of each pair is computed below.
    for i, j in itertools.combinations(sorted(nodes), 2):
        a, b = loc[i], loc[j]                                # the two locations (equal for same-location orders)
        # Two separate depot trips (to a, to b) versus one link a-b, shaped by lam.
        # Big saving = far places that sit close to each other (0 miles apart = biggest).
        out.append((float(d[depot, a] + d[depot, b] - lam * d[a, b]), i, j))
    # Sort key is a tuple: biggest saving first (the minus sign flips the order),
    # and equal savings go to the lower i, then the lower j (so runs are repeatable).
    out.sort(key=lambda t: (-t[0], t[1], t[2]))  # biggest saving first; ties by (i, j)
    return out


def _join(a: list[int], b: list[int], i: int, j: int) -> list[int] | None:
    """Join route a and route b so that node i (of a) meets node j (of b).

    Inputs:
        a, b: the two routes (nodes in visit order); i is in a, j is in b.
        i, j: the nodes to bring together.
    Output:
        the joined route (nodes in visit order), or None if i or j is not a
        route endpoint (an interior node cannot be joined without cutting its
        route). A route is reversed when needed: the matrix is symmetric, so
        a reversed route costs the same miles.
    """
    # WHY ENDPOINTS ONLY: a node in a route has exactly two neighbours (the one
    # before and the one after). An endpoint has the depot as one neighbour, so
    # the merge can delete that depot leg (this is the saving). An interior
    # node has no depot leg to delete, and linking it to another route would
    # give it three neighbours; making that legal means cutting one of its
    # links, which splits its route and creates a NEW trip to the depot.

    # --- Orient route a so that node i is its LAST node -----------------------
    # Step 1: make i the LAST stop of a (flip a if i is at its start).
    if a[-1] == i:
        first = a                    # i is already last: keep a as it is
    elif a[0] == i:
        first = a[::-1]              # i is first: flip the route ([::-1] reverses a list);
                                     # same miles, because d[i,j] == d[j,i]
    else:
        return None                  # i is in the middle: not an endpoint, no merge
    # --- Orient route b so that node j is its FIRST node ----------------------
    # Step 2: make j the FIRST stop of b (flip b if j is at its end).
    if b[0] == j:
        second = b                   # j is already first: keep b as it is
    elif b[-1] == j:
        second = b[::-1]             # j is last: flip b
    else:
        return None                  # j is in the middle: no merge
    # A route with one node passes both tests (it is first AND last), so a
    # single node can be joined on either side.
    return first + second            # [... i] + [j ...]: i and j are now neighbours


def solve(
    instance: Instance,
    params: Params | None = None,
    vehicle: VehicleType | None = None,
    *,
    lam: float = 1.0,
    resequence: bool = False,
    sequencing: str = "nn_2opt",
    split_orders: bool = False,
    max_exact_stops: int = 8,
    stats: dict | None = None,
) -> Solution:
    """Build a full plan with parallel Clarke-Wright savings.

    Inputs:
        instance: problem instance.
        params: limits to enforce; default instance.params.
        vehicle: vehicle type for every route; default the "Van" in params.
        lam: savings shape parameter (>= 0); 1.0 = textbook formula.
        resequence: False = keep the end-to-end order of a merge;
            True = re-order the merged stop set with `sequencing`.
        sequencing: method used when resequence=True (a key of
            sequencing.METHODS: "nn", "nn_2opt", "exact").
        split_orders: False = nodes are locations (a location's orders always
            ride together); True = nodes are single orders, so a location's
            orders may end up on different vans. Every order is delivered once.
        max_exact_stops: route size cap when sequencing="exact".
        stats: optional dict; if given it is filled with counts: pairs,
            negative (savings < 0), same_route, not_endpoint, infeasible,
            no_gain, merged (every pair lands in exactly one of the last five).
    Output:
        Solution (method "clarke_wright[lam=..,reseq=..]", with ",split=True"
        added when splitting; runtime in seconds).
        Raises ValueError for an unknown sequencing name, a negative lam, or
        a location (or, when splitting, an order) that does not fit one van alone.
    """
    # Step 0: bad options should fail now, with a clear message, not deep in the loop.
    if sequencing not in METHODS:
        raise ValueError(f"unknown sequencing {sequencing!r}; choose from {sorted(METHODS)}")
    if lam < 0:
        raise ValueError(f"lam must be >= 0, got {lam}")
    start = time.perf_counter()                              # stopwatch, for runtime_s at the end

    # --- One set of limits for everything -----------------------------------
    params = params or instance.params                       # no params given: use the data's own
    vehicle = vehicle or params.vehicle(DEFAULT_VEHICLE)     # no vehicle given: use the Van
    # Copy the instance with these params and this vehicle as the only type.
    # Why: route.py, sequencing and make_solution then all enforce the SAME limits.
    work = dataclasses.replace(
        instance, params=dataclasses.replace(params, vehicle_types=(vehicle,))
    )

    # --- Nodes: what a route is built from ----------------------------------
    # Together: one node per location (its id IS the location, it carries all
    # that location's orders). Split: one node per order (carries just that order).
    # Nodes = the things we merge: single orders when splitting, whole locations otherwise.
    if split_orders:
        nodes_all = sorted(int(o) for o in work.orders.index)
        location_of = {o: int(work.orders.loc[o, "LocationIndex"]) for o in nodes_all}
        node_orders = {o: [o] for o in nodes_all}
        label = "order"
    else:
        nodes_all = list(work.stops)                         # the 34 delivery stops, sorted
        location_of = {s: s for s in nodes_all}
        node_orders = {s: list(work.orders_at[s]) for s in nodes_all}
        label = "location"

    # stops_of turns a route of nodes into its location visits (route.py works with locations).
    def stops_of(route_nodes) -> list[int] | None:
        """Stops a route visits, in order. Back-to-back nodes at one location are
        ONE stop (two orders delivered in one visit). None if a location would be
        visited twice with something else in between (not allowed: one visit each)."""
        stops: list[int] = []
        for n in route_nodes:
            loc = location_of[n]  # the location this node is delivered at
            # Same location as the previous node: one visit, not a new stop.
            if stops and stops[-1] == loc:
                continue                                     # same location as the node before: same stop
            # The location came earlier and we left it: a second visit, which is not allowed.
            if loc in stops:
                return None                                  # came back to a place already visited
            stops.append(loc)
        return stops

    # orders_of lists every order delivered by a route's nodes.
    def orders_of(route_nodes) -> list[int]:
        """All orders carried by these nodes, in route order."""
        return [o for n in route_nodes for o in node_orders[n]]

    # --- Start: one route per node (depot -> node -> depot) -------------------
    routes: dict[int, list[int]] = {}                        # route id -> its nodes, in visit order
    miles: dict[int, float] = {}                             # route id -> its total miles
    for rid, n in enumerate(nodes_all):                      # rid = 0, 1, 2 ... one id per node
        m = route_metrics(stops_of([n]), orders_of([n]), work, vehicle)   # the one-node route's numbers
        if not m.feasible:                                   # a node that can't be served even alone
            raise ValueError(f"{label} {n} does not fit one {vehicle.name} alone")   # would be lost
        routes[rid] = [n]
        miles[rid] = m.miles_total
    route_of = {n: rid for rid, n in enumerate(nodes_all)}   # lookup: which route is each node on?

    # One counter per fate of a pair; every pair ends in exactly one of the last five.
    # Every pair lands in exactly one of these counters.
    counts = {"pairs": 0, "negative": 0, "same_route": 0, "not_endpoint": 0,
              "infeasible": 0, "no_gain": 0, "merged": 0}

    # --- Go through the savings, biggest first --------------------------------
    # Main loop: pairs from biggest saving to smallest; merge when every rule below passes.
    for saving, i, j in savings(work, nodes_all, lam, location_of):
        counts["pairs"] += 1
        if saving < 0:
            counts["negative"] += 1                          # only a statistic; the real skip rule is condition 4
        ra, rb = route_of[i], route_of[j]                    # the two routes this pair would join

        # Condition 1: different routes. Joining a route to itself would close a
        # loop that never returns to the depot.
        # Rule 1: i and j are already on the same route.
        if ra == rb:
            counts["same_route"] += 1
            continue                                         # skip this pair, go to the next
        # Condition 2: both nodes are route endpoints (see _join for why).
        # _join also flips routes so that i and j end up next to each other.
        # Rule 2: only a route's two end stops can be joined.
        joined = _join(routes[ra], routes[rb], i, j)
        if joined is None:                                   # i or j is an interior node
            counts["not_endpoint"] += 1
            continue

        # Condition 3: the merged route passes all four limits.
        joined_stops = stops_of(joined)                      # the stops the merged route would visit
        if joined_stops is None:                             # it would visit a location twice
            counts["infeasible"] += 1
            continue
        merged_orders = orders_of(joined)                    # every order on the merged route
        # Rule 3: the merged route must be feasible on all four limits.
        if resequence:
            # Exact search refuses big sets: count "too big" as "does not fit".
            if sequencing == "exact" and len(joined_stops) > max_exact_stops:
                counts["infeasible"] += 1
                continue
            # Ask sequencing for the best legal order of the merged SET of stops
            # (not just the end-to-end order that _join produced).
            r = best_sequence(joined_stops, merged_orders, work, vehicle,
                              method=sequencing, max_exact_stops=max_exact_stops)
            if r.sequence is None:                           # no legal order found
                counts["infeasible"] += 1
                continue
            # Rebuild the node order to follow the new stop order (nodes at one
            # location stay together, in their current relative order).
            # Group the merged nodes by location, then lay them out in the new stop order.
            by_stop: dict[int, list[int]] = {}
            for n in joined:
                by_stop.setdefault(location_of[n], []).append(n)
            new_nodes = [n for s in r.sequence for n in by_stop[s]]
            new_miles = r.metrics.miles_total
        else:
            # Keep the end-to-end order exactly as joined; route.py judges it.
            m = route_metrics(joined_stops, merged_orders, work, vehicle)
            if not m.feasible:
                counts["infeasible"] += 1
                continue
            new_nodes, new_miles = joined, m.miles_total

        # Condition 4: REAL miles must drop. The saving score only RANKS pairs
        # (at lam != 1 it is not true miles), so check the actual miles here:
        # never accept a merge that makes the plan longer.
        # Rule 4: the merge must cut real miles, not just show a positive saving on paper.
        if new_miles >= miles[ra] + miles[rb]:
            counts["no_gain"] += 1
            continue

        # All four conditions hold: merge. Route ra takes over, route rb disappears.
        routes[ra], miles[ra] = new_nodes, new_miles
        del routes[rb]  # route rb is absorbed into route ra
        for n in new_nodes:                                  # every node now belongs to route ra
            route_of[n] = ra
        counts["merged"] += 1

    # --- Package the result ------------------------------------------------------
    if stats is not None:                                    # the caller asked for the counts
        stats.update(counts)
    runtime = time.perf_counter() - start                    # seconds the whole build took
    # The method name records the options used, so a saved plan says how it was made.
    # ",split=True" is only added when splitting, so older labels stay unchanged.
    method = (f"clarke_wright[lam={lam},reseq={resequence}" + (f",{sequencing}" if resequence else "")
              + (",split=True" if split_orders else "") + "]")
    # Routes are numbered by their smallest stop (then stops, then orders): repeatable, easy to read.
    specs = []
    for route_nodes in routes.values():
        stops = stops_of(route_nodes)
        specs.append((vehicle.name, stops, orders_of(route_nodes)))
    specs.sort(key=lambda s: (min(s[1]), s[1], s[2]))  # stable route numbering: by smallest stop
    # make_solution recomputes every route's numbers with route.py.
    # make_solution measures every route with route.py and numbers them 1..n.
    return make_solution(specs, work, method=method, runtime_s=runtime)
