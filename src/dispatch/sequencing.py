"""Find a feasible/cheap ORDER for a given stop SET.

Given which stops a van visits (and which orders it carries), choose the
visit order: feasible on all four limits and, among feasible orders, the
cheapest in total miles. Feasibility is ALWAYS decided by
``route.route_metrics(...).feasible``; this module never re-implements it.

Method ladder (each rung adds one idea, so its gain can be measured;
see experiments/sequencing_ladder.py and LADDER.md)
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
    d = inst.dist_mi
    return float(sum(d[seq[t], seq[t + 1]] for t in range(len(seq) - 1)))


def _total_miles(seq: Sequence[int], inst: Instance) -> float:
    """Depot -> seq[0] + inter-stop + seq[-1] -> depot (mi). 0 if empty."""
    if len(seq) == 0:
        return 0.0
    d = inst.dist_mi
    depot = inst.depot_index
    return float(d[depot, seq[0]]) + _interstop_miles(seq, inst) + float(d[seq[-1], depot])


def _result(seq, m, method, proven, evaluations, scored) -> SequenceResult:
    """Package a result; sequence becomes None if the order is infeasible."""
    sequence = tuple(seq) if m.feasible else None
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
    remaining = set(stops)
    path: list[int] = []
    current = start
    if start in remaining:          # open path starting at a stop
        path.append(start)
        remaining.remove(start)
    while remaining:
        # min over (distance, index): nearest first, lower index on ties.
        current = min(remaining, key=lambda s: (d[current, s], s))
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
    best = list(seq)
    best_cost = cost(best)
    n_costed = 1                    # the starting order
    improved = True
    while improved:
        improved = False
        for a in range(len(best) - 1):
            for b in range(a + 1, len(best)):
                # Reverse the segment best[a..b] (inclusive).
                candidate = best[:a] + best[a:b + 1][::-1] + best[b + 1:]
                c = cost(candidate)
                n_costed += 1
                if c < best_cost:
                    best, best_cost = candidate, c
                    improved = True
                    break          # restart the scan from the new order
            if improved:
                break
    return best, n_costed


def _empty(orders_on_route, instance, vehicle, method, proven) -> SequenceResult:
    """Result for an empty stop set: the van is not dispatched."""
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
    tour = _nearest_neighbor(stops, instance.depot_index, instance)
    m = route_metrics(tour, orders_on_route, instance, vehicle)
    return _result(tour, m, NN, False, 1, 1)


# --- rung 1: nearest neighbour + 2-opt ------------------------------------------

def _nn_2opt_tour(stops: Sequence[int], instance: Instance) -> tuple[list[int], int]:
    """NN tour from the depot improved by 2-opt on total miles.

    Output: (tour, orders scored = 1 for the NN tour + those 2-opt costed).
    """
    tour = _nearest_neighbor(stops, instance.depot_index, instance)
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
    if len(stops) > max_exact_stops:
        raise ValueError(
            f"{len(stops)} stops exceeds max_exact_stops={max_exact_stops}"
        )
    if len(stops) == 0:
        return _empty(orders_on_route, instance, vehicle, EXACT, True)
    # Sorted start so permutations come out in a fixed, reproducible order.
    base = tuple(sorted(stops))

    # A route and its mirror image cost the same only if d[i,j] == d[j,i].
    symmetric = bool(np.array_equal(instance.dist_mi, instance.dist_mi.T))

    # Score every order: (total miles, inter-stop miles, order).
    scored = []
    for perm in itertools.permutations(base):
        # Skip one of each mirror pair (e.g. keep 1-2-3, skip 3-2-1).
        if symmetric and perm[0] > perm[-1]:
            continue
        scored.append((_total_miles(perm, instance), _interstop_miles(perm, instance), perm))
    # Cheapest total first; ties broken by inter-stop miles, then the tuple.
    scored.sort()

    # Walk from cheapest. Because totals only go up as we walk, an order is
    # hopeless if an earlier FAILED order had inter-stop miles <= its own
    # (see "Key fact" in the module docstring). Track the smallest failed one.
    evaluations = 0
    min_failed_interstop = float("inf")
    for total, inter, perm in scored:
        if inter >= min_failed_interstop:
            continue   # dominated by a failed order: cannot pass
        m = route_metrics(perm, orders_on_route, instance, vehicle)
        evaluations += 1
        if m.feasible:
            # First feasible in cost order = cheapest feasible.
            return SequenceResult(perm, m, EXACT, True, evaluations, len(scored))
        min_failed_interstop = inter

    # No order passed. Report the order with the least inter-stop miles
    # (the best possible span) so the caller sees the shortfall.
    closest = min(scored, key=lambda s: (s[1], s[0], s[2]))[2]
    m = route_metrics(closest, orders_on_route, instance, vehicle)
    evaluations += 1
    return SequenceResult(None, m, EXACT, True, evaluations, len(scored))


# --- registry and dispatcher ------------------------------------------------------

# Every rung by name, so benchmarks and solvers can select one.
METHODS: dict[str, Callable[..., SequenceResult]] = {
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
    if method not in METHODS:
        raise ValueError(f"unknown method {method!r}; choose from {sorted(METHODS)}")
    if method == "exact":
        return exact_sequence(stops, orders_on_route, instance, vehicle, max_exact_stops)
    return METHODS[method](stops, orders_on_route, instance, vehicle)
