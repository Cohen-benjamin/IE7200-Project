"""Find a feasible/cheap ORDER for a given stop SET.

Given which stops a van visits (and which orders it carries), choose the
visit order: feasible on all four limits and, among feasible orders, the
cheapest in total miles. Feasibility is ALWAYS decided by
``route.route_metrics(...).feasible``; this module never re-implements it.

Method ladder (each rung adds one idea, so its gain can be measured;
see LADDER.md)
------------------------------------------------------------------------
    rung 0  nn_sequence         nearest-neighbour tour from the depot
    rung 1  nn_2opt_sequence    rung 0 + 2-opt on total miles
    ref     exact_sequence      every order; proven optimal / infeasible
Known limitation: both heuristic rungs minimise TOTAL miles only. On a
span-bound set the cheapest tour can break span while another order is
legal; only exact_sequence finds that order (e.g. the 12-stop route in
LADDER.md is reported infeasible by both rungs).
Every result also reports its effort: ``evaluations`` (route_metrics
calls) and ``orders_scored`` (complete visit orders built or costed).

Key fact (used by exact_sequence)
---------------------------------
For a fixed stop set and fixed orders, volume and unload time are the same
in every order. The visit order changes only two numbers:
    total miles       -> drive (<= 660) and duty (<= 840)
    inter-stop miles  -> span  (<= 600)
Every limit is "<=". So if order A fails, any order B with total >= A's AND
inter-stop >= A's must fail too: all of B's metrics are at least A's.
(M2 caveat: dock-wave departure times make the first depot leg matter on
its own, which breaks this two-number argument.)


Units: miles, minutes, ft3.
"""
from __future__ import annotations

import itertools
from typing import Callable, NamedTuple, Sequence

import numpy as np

from dispatch.data import Instance
from dispatch.params import VehicleType
from dispatch.route import RouteMetrics, route_metrics

# method_used labels (names, not model parameters).
NN = "nn"
NN_2OPT = "nn_2opt"
EXACT = "exact"


# NamedTuple = a small read-only record whose fields can be read by name (result.sequence).
class SequenceResult(NamedTuple):
    """Outcome of sequencing one stop set.

    Attributes:
        sequence: chosen visit order (LocationIndex tuple), or None if no
            feasible order was found.
        metrics: RouteMetrics of the chosen order; if none was feasible, of
            the last attempt, so the caller can see by how much it misses.
        method_used: which method produced the result: "nn", "nn_2opt"
            or "exact".
        proven: True only for exact results: the order is the cheapest
            feasible one, or (sequence None) no feasible order exists.
        evaluations: number of route_metrics calls made (feasibility checks).
        orders_scored: number of complete visit orders built or costed in
            miles. Measures search effort independent of the computer.
    """

    sequence: tuple[int, ...] | None
    metrics: RouteMetrics
    method_used: str
    proven: bool
    evaluations: int
    orders_scored: int


# --- objectives (distances only; NOT feasibility) ---------------------------

def _interstop_miles(seq: Sequence[int], inst: Instance) -> float:
    """Miles between consecutive stops, depot legs excluded (mi)."""
    d = inst.dist_mi  # d[i, j] = miles from i to j
    # Add up each leg seq[t] -> seq[t+1]; N stops have N-1 legs between them.
    return float(sum(d[seq[t], seq[t + 1]] for t in range(len(seq) - 1)))


def _total_miles(seq: Sequence[int], inst: Instance) -> float:
    """Depot -> seq[0] + inter-stop + seq[-1] -> depot (mi). 0 if empty."""
    if len(seq) == 0:  # no stops = the van stays home = 0 miles
        return 0.0
    d = inst.dist_mi
    depot = inst.depot_index
    # depot -> first stop, + the legs between stops, + last stop -> depot.
    return float(d[depot, seq[0]]) + _interstop_miles(seq, inst) + float(d[seq[-1], depot])


def _result(seq, m, method, proven, evaluations, scored) -> SequenceResult:
    """Package a result; sequence becomes None if the order is infeasible."""
    sequence = tuple(seq) if m.feasible else None  # None tells the caller 'no legal order found'
    return SequenceResult(sequence, m, method, proven, evaluations, scored)


# --- building blocks -----------------------------------------------------------

def _nearest_neighbor(stops: Sequence[int], start: int, inst: Instance) -> list[int]:
    """Greedy path: from `start`, repeatedly go to the closest unvisited stop.

    Inputs:
        stops: stops to order.
        start: where the path begins (the depot for a closed route, or one
            of the stops for an open path). A start stop is included first.
        inst: problem instance.
    Output:
        list of all stops in visit order (depot never included).
        Ties go to the lower LocationIndex, so the result is reproducible.
    """
    d = inst.dist_mi
    remaining = set(stops)  # stops not visited yet
    path: list[int] = []  # the visit order being built
    current = start
    if start in remaining:          # open path starting at a stop
        path.append(start)
        remaining.remove(start)
    while remaining:
        # min over (distance, index): nearest first, lower index on ties.
        current = min(remaining, key=lambda s: (d[current, s], s))  # min() over (distance, index) pairs
        path.append(current)
        remaining.remove(current)
    return path


def _two_opt(
    seq: list[int], cost: Callable[[Sequence[int]], float]
) -> tuple[list[int], int]:
    """Improve an order by reversing segments while that lowers `cost`.

    Inputs:
        seq: starting order.
        cost: function giving the cost (miles) of an order.
    Output:
        (order, n_costed): a 2-opt local optimum (no single segment reversal
        lowers the cost) and how many orders were costed to reach it.
    Notes:
        The full cost is recomputed for every move (no shortcut formulas),
        so it stays correct on this non-metric matrix. First improvement is
        accepted and the scan restarts; the fixed loop order makes it
        deterministic.
    """

    best = list(seq)                # copy, so the caller's list is untouched
    best_cost = cost(best)          # miles of the order we start from
    n_costed = 1                    # count of orders measured (start = 1)
    improved = True                 # True so the while-loop runs at least once
    while improved:                 # keep going while the last pass found a gain
        improved = False            # assume no gain this pass until we find one
        for a in range(len(best) - 1):          # a = first position of the stretch
            for b in range(a + 1, len(best)):   # b = last position (always after a)
                # Build the new order in three pieces:
                #   best[:a]            the part before the stretch, unchanged
                #   best[a:b+1][::-1]   the stretch a..b, reversed ([::-1] flips a list)
                #   best[b+1:]          the part after the stretch, unchanged
                candidate = best[:a] + best[a:b + 1][::-1] + best[b + 1:]
                c = cost(candidate)             # miles of the flipped order
                n_costed += 1                   # one more order measured
                if c < best_cost:               # shorter? keep it
                    best, best_cost = candidate, c
                    improved = True             # remember we found a gain
                    break                       # leave the inner loop...
            if improved:
                break                           # ...and the outer loop, then
                                                # the while-loop starts over
                                                # from the new, shorter order
    # Here no single flip shortens the route any more: a "local optimum".
    # It is NOT guaranteed to be the best order overall (only exact is).
    return best, n_costed


def _empty(orders_on_route, instance, vehicle, method, proven) -> SequenceResult:
    """Result for an empty stop set: the van is not dispatched."""
    # An empty route: the van is not dispatched, so every number is zero.
    m = route_metrics((), orders_on_route, instance, vehicle)
    return SequenceResult((), m, method, proven, 1, 0)


# --- rung 0: nearest neighbour ------------------------------------------------

def nn_sequence(
    stops: Sequence[int],
    orders_on_route: Sequence[int],
    instance: Instance,
    vehicle: VehicleType,
) -> SequenceResult:
    """Rung 0: nearest-neighbour tour from the depot, no improvement.

    Inputs:
        stops: the stop set (LocationIndex values, depot excluded).
        orders_on_route: OrderIndex values the van carries.
        instance: problem instance.
        vehicle: VehicleType doing the route.
    Output:
        SequenceResult, method "nn", proven False, 1 evaluation,
        1 order scored. sequence None if the tour is infeasible.
    """
    if len(stops) == 0:
        return _empty(orders_on_route, instance, vehicle, NN, False)
    # Rung 0: build the greedy tour, then let route.py judge it (no re-implemented rules here).
    tour = _nearest_neighbor(stops, instance.depot_index, instance)
    m = route_metrics(tour, orders_on_route, instance, vehicle)
    return _result(tour, m, NN, False, 1, 1)  # False = not proven best; 1 check, 1 order built


# --- rung 1: nearest neighbour + 2-opt ------------------------------------------

def _nn_2opt_tour(stops: Sequence[int], instance: Instance) -> tuple[list[int], int]:
    """NN tour from the depot improved by 2-opt on total miles.

    Output: (tour, orders scored = 1 for the NN tour + those 2-opt costed).
    """
    # Step 1: a quick first order from the greedy nearest-neighbour rule.
    tour = _nearest_neighbor(stops, instance.depot_index, instance)
    # Step 2: improve it with 2-opt. The "lambda s: ..." is a tiny unnamed
    # function telling 2-opt how to measure an order: total miles, depot
    # legs included.
    tour, n_costed = _two_opt(tour, lambda s: _total_miles(s, instance))
    # n_costed already counts the NN tour as 2-opt's starting order.
    return tour, n_costed


def nn_2opt_sequence(
    stops: Sequence[int],
    orders_on_route: Sequence[int],
    instance: Instance,
    vehicle: VehicleType,
) -> SequenceResult:
    """Rung 1: rung 0's tour improved by 2-opt on TOTAL miles.

    Inputs: as nn_sequence.
    Output:
        SequenceResult, method "nn_2opt", proven False. Note: fewer miles can
        mean MORE inter-stop miles, so this rung can break span on a set
        that rung 0 served feasibly (see the synthetic test).
    """
    if len(stops) == 0:
        return _empty(orders_on_route, instance, vehicle, NN_2OPT, False)
    tour, scored = _nn_2opt_tour(stops, instance)
    m = route_metrics(tour, orders_on_route, instance, vehicle)
    return _result(tour, m, NN_2OPT, False, 1, scored)


# --- reference: exact ------------------------------------------------------------

def exact_sequence(
    stops: Sequence[int],
    orders_on_route: Sequence[int],
    instance: Instance,
    vehicle: VehicleType,
    max_exact_stops: int = 8,
) -> SequenceResult:
    """Cheapest feasible order by trying every order (proven result).

    Inputs:
        stops, orders_on_route, instance, vehicle: as nn_sequence.
        max_exact_stops: refuse sets larger than this (runtime grows as k!).
    Output:
        SequenceResult with method_used "exact" and proven True. sequence is
        the feasible order with fewest total miles (ties: lowest inter-stop
        miles, then lowest tuple), or None if no order is feasible.
        Raises ValueError if len(stops) > max_exact_stops.
    """

    # Too many stops would take too long (k stops = k! orders), so refuse.
    if len(stops) > max_exact_stops:
        raise ValueError(
            f"{len(stops)} stops exceeds max_exact_stops={max_exact_stops}"
        )
    # No stops: nothing to order; return the "van not dispatched" result.
    if len(stops) == 0:
        return _empty(orders_on_route, instance, vehicle, EXACT, True)
    # Sort the stops first so the list of orders is the same on every run.
    base = tuple(sorted(stops))

    # A route driven backwards (3-2-1 instead of 1-2-3) has the same miles
    # ONLY if the distance A->B always equals B->A. Check that once here.
    # .T is the transposed matrix; array_equal is True if they match exactly.
    symmetric = bool(np.array_equal(instance.dist_mi, instance.dist_mi.T))

    # --- Step 1: list every order with its two mileage numbers --------------
    scored = []                                   # will hold (total, inter, order)
    # permutations(base) yields every possible ordering of the stops,
    # one tuple at a time: (1,2,3), (1,3,2), (2,1,3), (2,3,1), ...
    for perm in itertools.permutations(base):
        # Keep only one of each mirror pair: 1-2-3 is kept (1 < 3),
        # its mirror 3-2-1 is skipped (3 > 1). Halves the work.
        if symmetric and perm[0] > perm[-1]:
            continue                              # skip this one, go to next
        # Store total miles (drive and duty), inter-stop miles (span), order.
        scored.append((_total_miles(perm, instance), _interstop_miles(perm, instance), perm))
    # Sorting a list of tuples compares the first item, then the second on
    # ties, then the third: so cheapest total first, then least inter-stop.
    scored.sort()

    # --- Step 2: check orders from cheapest, skipping hopeless ones ---------
    # Shortcut ("Key fact" in the module docstring): we walk in order of
    # rising total miles. If an earlier order FAILED and this one has at
    # least as many inter-stop miles, every number of this one is at least
    # as bad, so it must fail too. We only need to remember the smallest
    # inter-stop miles among the failures so far.
    evaluations = 0                               # how many full checks we ran
    min_failed_interstop = float("inf")           # "infinity": nothing failed yet
    for total, inter, perm in scored:             # unpack each stored tuple
        if inter >= min_failed_interstop:
            continue                              # can't pass: don't even check
        # Ask route.py for the real verdict on all four limits.
        m = route_metrics(perm, orders_on_route, instance, vehicle)
        evaluations += 1                          # one more full check done
        if m.feasible:
            # First legal order in cheapest-first order = cheapest legal
            # order. proven=True because every cheaper order was ruled out.
            return SequenceResult(perm, m, EXACT, True, evaluations, len(scored))
        # It failed: remember its inter-stop miles for the shortcut above.
        min_failed_interstop = inter

    # --- Step 3: nothing passed (proof that the set is infeasible) ----------
    # Report the order with the fewest inter-stop miles (the best span any
    # order can get), so the caller can see how far off it is.
    # key=... sorts by inter-stop (s[1]), then total (s[0]), then the order
    # (s[2]); [2] at the end takes just the order out of the winning tuple.
    closest = min(scored, key=lambda s: (s[1], s[0], s[2]))[2]
    m = route_metrics(closest, orders_on_route, instance, vehicle)
    evaluations += 1
    # sequence=None means "no legal order"; proven=True because we checked all.
    return SequenceResult(None, m, EXACT, True, evaluations, len(scored))


# --- registry and dispatcher ------------------------------------------------------

# Every rung by name, so benchmarks and solvers can select one.
METHODS: dict[str, Callable[..., SequenceResult]] = {  # name -> function; lets the caller choose a method by text
    "nn": nn_sequence,
    "nn_2opt": nn_2opt_sequence,
    "exact": exact_sequence,
}


def best_sequence(
    stops: Sequence[int],
    orders_on_route: Sequence[int],
    instance: Instance,
    vehicle: VehicleType,
    method: str,
    max_exact_stops: int = 8,
) -> SequenceResult:
    """Sequence a stop set with an explicitly chosen rung.

    There is no automatic choice: each solver states which rung it uses.

    Inputs:
        stops, orders_on_route, instance, vehicle: as nn_sequence.
        method: required; a key of METHODS ("nn", "nn_2opt", "exact").
        max_exact_stops: size limit for exact search; used only when
            method is "exact", ignored otherwise.
    Output:
        SequenceResult of the chosen method. Raises ValueError for an
        unknown method name (and exact_sequence raises ValueError if the
        set exceeds max_exact_stops).
    """
    # Fail loudly on a typo instead of silently using some other method.
    if method not in METHODS:
        raise ValueError(f"unknown method {method!r}; choose from {sorted(METHODS)}")
    if method == "exact":
        return exact_sequence(stops, orders_on_route, instance, vehicle, max_exact_stops)
    # Look up the function by name, then call it with the same inputs.
    return METHODS[method](stops, orders_on_route, instance, vehicle)
