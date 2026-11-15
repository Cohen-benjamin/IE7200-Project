"""Exhaustive enumeration solver: the true optimum on a SMALL subset of stops.

Why it exists
-------------
Brief section 4.1: brute force on 6-9 stops is the only place you will ever
know the true global optimum, so it is the only place a heuristic's error
can be measured exactly (run nearest neighbour on the same subset and compare).

How it works
------------
1. A "partition" groups the stops into routes (the order of the routes does
   not matter). Enumerate EVERY partition.
2. For each group of stops (a "block"), find its best legal visiting order
   with exact sequencing. Each block is solved once and remembered.
3. A partition is feasible only if every block is. Add up the blocks' miles
   and keep the cheapest feasible partition.

How many partitions? (Bell numbers)
-----------------------------------
The number of ways to split n stops into routes is the Bell number B(n):
    B(6) = 203     B(7) = 877      B(8) = 4,140     B(9) = 21,147
    B(10) = 115,975    B(12) = 4,213,597    B(34) ~ 2.1 x 10^28
That growth is why the full 34-stop problem is out of reach and why this
solver refuses more than max_stops (default 9) stops.

Runtime
-------
Re-sequencing a block for every partition would be wasteful. There are only
2^n - 1 distinct blocks (511 for n = 9), so each is sequenced exactly once
(remembered in `memo`) and partitions just add stored miles. The cost is
dominated by the largest blocks (exact sequencing is about k! work): measured
7 stops 0.03 s, 8 stops 0.13 s, 9 stops 1.3 s, about 4 s for a whole 9-stop
subset. Summing the 21,147 partitions is then instant.

Scope: optimal among plans that keep each location's orders on ONE van.
(Splitting orders would mean partitioning ORDERS, whose Bell number is far
larger: B(12) is already 4.2 million.)

Units: miles, minutes, ft3.
"""
from __future__ import annotations

import dataclasses
import random
import time
from typing import Iterator, Sequence

import pandas as pd

from dispatch.data import Instance
from dispatch.params import Params, VehicleType
from dispatch.sequencing import exact_sequence
from dispatch.solution import Solution, make_solution

# Vehicle used when none is given (M1 fleet). A name, not a model number.
DEFAULT_VEHICLE = "Van"
# Largest subset solved: B(9) = 21,147 partitions, about 4 s.
DEFAULT_MAX_STOPS = 9


def set_partitions(items: Sequence[int]) -> Iterator[list[tuple[int, ...]]]:
    """Every way to group `items` into non-empty blocks (a set partition).

    Inputs:
        items: the things to group, e.g. stop numbers.
    Output:
        iterator of partitions; each is a list of tuples (the blocks). There
        are exactly B(n) of them (the Bell number): 1, 1, 2, 5, 15, 52, 203...
        Items inside a block keep their order from `items`.
    """
    # Freeze the input as a tuple, so it cannot change while we recurse.
    items = tuple(items)

    # build() is a generator: it hands back one finished partition at a time (yield)
    # instead of storing all of them in memory.
    def build(i: int, blocks: list[list[int]]):
        """Place item i, then recurse on item i + 1."""
        if i == len(items):                                  # every item placed: one partition done
            yield [tuple(b) for b in blocks]                 # copy, because `blocks` keeps changing
            return
        # Choice 1: put item i into each existing block in turn.
        for b in blocks:
            b.append(items[i])
            yield from build(i + 1, blocks)
            b.pop()                                          # undo, so the next choice starts clean
        # Choice 2: start a new block containing only item i.
        blocks.append([items[i]])
        yield from build(i + 1, blocks)
        blocks.pop()                                         # undo

    yield from build(0, [])


def restrict_instance(instance: Instance, stops: Sequence[int]) -> Instance:
    """The same problem, but with ONLY the orders delivered at `stops`.

    Inputs:
        instance: the full instance.
        stops: LocationIndex values to keep (depot excluded).
    Output:
        Instance with the same distance matrix and indices, but only those
        stops' orders. Solvers, Solution and validate_plan then see exactly
        the subset's problem (e.g. "every order delivered" means the subset's).
        Derived location columns are recomputed from the kept orders.
    """
    keep = set(int(s) for s in stops)  # a set makes the membership test below fast
    orders = instance.orders[instance.orders["LocationIndex"].isin(keep)]   # subset's orders  # isin() keeps only rows whose location is in keep
    # Keep the depot row and the chosen stops' rows of the locations table.
    locations = instance.locations.loc[
        [instance.depot_index, *sorted(keep)]
    ].copy()
    # The two derived columns would still describe the FULL instance: recompute.
    locations["OrderCount"] = orders.groupby("LocationIndex").size().reindex(locations.index, fill_value=0)
    locations["TotalVolume_ft3"] = (
        orders.groupby("LocationIndex")["Volume_ft3"].sum().reindex(locations.index, fill_value=0)
    )
    # orders_at (location -> its order numbers) is rebuilt for the kept stops only.
    orders_at = {s: instance.orders_at[s] for s in sorted(keep)}
    # replace() copies the frozen Instance with these three fields swapped; the matrix is shared.
    return dataclasses.replace(instance, orders=orders, locations=locations, orders_at=orders_at)


def draw_subset(instance: Instance, k: int, seed: int, mode: str = "random") -> tuple[int, ...]:
    """Pick k stops, reproducibly.

    Inputs:
        instance: the full instance.
        k: how many stops (1 to the number of stops).
        seed: random seed; the same seed always gives the same subset.
        mode: "random" = k stops chosen at random;
              "clustered" = a randomly chosen stop plus its k - 1 nearest
              stops by distance (ties -> lower LocationIndex), a
              geographically tight group like a real route.
    Output:
        sorted tuple of LocationIndex values.
    """
    stops = instance.stops                                   # sorted tuple of the 34 stops
    if not 1 <= k <= len(stops):
        raise ValueError(f"k must be between 1 and {len(stops)}, got {k}")
    # A seed fixes the 'random' choices, so every run (and every professor) gets the same subset.
    rng = random.Random(seed)                                # own generator: no global state touched
    if mode == "random":
        return tuple(sorted(rng.sample(stops, k)))           # k different stops, uniformly
    if mode == "clustered":
        seed_stop = rng.choice(stops)                        # centre of the cluster
        d = instance.dist_mi
        # Nearest first; the seed stop itself is 0 miles away, so it comes first.
        nearest = sorted(stops, key=lambda s: (d[seed_stop, s], s))[:k]
        return tuple(sorted(nearest))
    raise ValueError(f"unknown mode {mode!r}; use 'random' or 'clustered'")


def solve(
    instance: Instance,
    params: Params | None = None,
    vehicle: VehicleType | None = None,
    *,
    stops: Sequence[int],
    max_stops: int = DEFAULT_MAX_STOPS,
) -> Solution:
    """Find the minimum-mile feasible plan for a small subset of stops.

    Inputs:
        instance: problem instance (the full one; only `stops` are solved).
        params: limits to enforce; default instance.params.
        vehicle: vehicle type for every route; default the "Van" in params.
        stops: the subset to solve (LocationIndex values). Required.
        max_stops: refuse larger subsets (the work grows as the Bell number).
    Output:
        Solution for the subset's orders, method "brute[<n> stops]". Ties on
        miles go to fewer routes, then the smallest partition, so the result
        is deterministic. Validate it against restrict_instance(instance, stops).
        Raises ValueError for too many, repeated or unknown stops.
    """
    # --- Check the request -------------------------------------------------
    stops = tuple(sorted(int(s) for s in stops))             # sorted: same answer for any input order
    if len(stops) > max_stops:
        raise ValueError(f"{len(stops)} stops exceeds max_stops={max_stops}")
    if len(set(stops)) != len(stops):
        raise ValueError(f"repeated stops in {list(stops)}")
    unknown = set(stops) - set(instance.orders_at)
    if unknown:
        raise ValueError(f"unknown stops: {sorted(unknown)}")
    start = time.perf_counter()                              # stopwatch, for runtime_s at the end

    # --- One set of limits, and the subset's problem -------------------------
    params = params or instance.params                       # no params given: use the data's own
    vehicle = vehicle or params.vehicle(DEFAULT_VEHICLE)     # no vehicle given: use the Van
    work = dataclasses.replace(
        restrict_instance(instance, stops),
        params=dataclasses.replace(params, vehicle_types=(vehicle,)),
    )

    # --- Step 1: solve every possible block ONCE -------------------------------
    n = len(stops)  # number of stops in this subset
    # memo = notebook of answers: block of stops -> (best miles, best order), or None if no legal order.
    memo: dict[frozenset, tuple[float, tuple[int, ...]] | None] = {}
    # Bit trick: counting 1 .. 2^n-1 in binary lists every non-empty block once.
    # Example: 0b101 means stops 0 and 2 are in the block.
    for mask in range(1, 2 ** n):                            # each non-empty subset, as a bit pattern
        block = tuple(stops[j] for j in range(n) if mask >> j & 1)    # bit j set = stop j is in
        block_orders = [o for s in block for o in work.orders_at[s]]  # all orders at those stops
        # Exact sequencing: the best legal order, or proof that none exists.
        r = exact_sequence(block, block_orders, work, vehicle, max_exact_stops=len(block))
        # Remember miles and order, or None when exact sequencing proved the block cannot be served.
        memo[frozenset(block)] = (r.metrics.miles_total, r.sequence) if r.sequence is not None else None

    # --- Step 2: try every partition, keep the cheapest feasible one -------------
    best_key, best_partition = None, None  # nothing found yet
    # Each partition is one way of splitting the stops into routes. Its cost = sum of its blocks' stored miles.
    for partition in set_partitions(stops):
        total = 0.0
        for block in partition:
            entry = memo[frozenset(block)]
            if entry is None:                                # one block can't be served: skip it all
                break
            total += entry[0]                                # add this block's miles
        # for/else: the else part runs only when the loop finished without break.
        else:                                                # no break: every block was feasible
            # Smaller key wins: fewer miles, then fewer routes, then smallest partition.
            key = (total, len(partition), tuple(sorted(tuple(sorted(b)) for b in partition)))
            if best_key is None or key < best_key:
                best_key, best_partition = key, partition

    # --- Build the plan from the winning partition -------------------------------
    if best_partition is None:                               # cannot happen when stops is empty or
        best_partition = []                                  # singles are feasible; keep it explicit
    # Turn the winning partition into (vehicle, stops, orders) tuples that make_solution() understands.
    routes = []
    for block in sorted(best_partition, key=lambda b: min(b)):   # routes numbered by smallest stop
        sequence = memo[frozenset(block)][1]                 # the block's best visiting order
        routes.append((vehicle.name, list(sequence), [o for s in sequence for o in work.orders_at[s]]))
    runtime = time.perf_counter() - start  # seconds since the stopwatch started
    return make_solution(routes, work, method=f"brute[{n} stops]", runtime_s=runtime)
