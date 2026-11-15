"""Nearest-neighbour construction heuristic (rung 0 of the solver ladder).

How it works
------------
Build routes one at a time. A route starts at the depot; from the current
position it goes to the NEAREST location that still has unserved orders AND
whose orders still fit on the route. "Fit" means the tentative route passes
all four limits, decided by sequencing the tentative stop set (span depends
on the visit order). When nothing fits, the route closes and a new one
starts. Repeat until every order is served.

What "split orders" means
-------------------------
Some locations receive several orders (8 of the 34 do). The option
split_orders decides whether those orders must ride on the SAME van:
- split_orders=False ("together"): all orders at a location go on one van.
  If they do not all fit, the whole location waits for a later route.
  Each location is visited by exactly one van.
- split_orders=True: a location's orders may be divided between vans, so
  one location can be visited by more than one van.

Tie-break rule (fully deterministic)
------------------------------------
- "Current position" = the location added last (not the last stop of the
  re-sequenced route).
- Equal distances -> the lower LocationIndex wins.
- With split_orders=True, a location's orders are tried in OrderIndex order.

Where nearest neighbour is myopic on this instance
--------------------------------------------------
- It always starts with the stops nearest the depot and uses them up first.
  The 201-mile store (location 14) can only share a route with near-depot
  stops (3, 4, 5, 6, 7, 10); every other partner pushes driving over 660
  min. By the time NN reaches location 14 those partners are usually
  gone, so it drives 402 miles alone. NN never saves a partner for a hard
  stop. (Measured later: pairing it with its best partner would save only
  1-4 miles, so this costs little; Clarke-Wright also leaves it alone. NN's
  larger loss is in how it groups the OTHER 33 stops.)
- It never looks ahead: it closes a route as soon as the nearest remaining
  location does not fit, so the last routes are leftovers far apart.

Units: miles, minutes, ft3.
"""
from __future__ import annotations

import dataclasses
import time

from dispatch.data import Instance
from dispatch.params import Params, VehicleType
from dispatch.sequencing import METHODS, best_sequence
from dispatch.solution import Solution, make_solution

# Vehicle used when none is given (M1 fleet). A name, not a model number.
DEFAULT_VEHICLE = "Van"


def solve(
    instance: Instance,
    params: Params | None = None,
    vehicle: VehicleType | None = None,
    *,
    sequencing: str = "nn",
    split_orders: bool = False,
    max_exact_stops: int = 8,
) -> Solution:
    """Build a full plan with nearest neighbour.

    Inputs:
        instance: problem instance.
        params: limits to enforce; default instance.params.
        vehicle: vehicle type for every route; default the "Van" in params.
        sequencing: how each tentative route is ordered and checked; a key
            of sequencing.METHODS ("nn", "nn_2opt", "exact").
        split_orders: False = all orders at a location ride on one van (or
            wait for a later route); True = they may be divided between
            vans. Every order is delivered exactly once either way.
        max_exact_stops: route size cap when sequencing="exact" (a bigger
            tentative route counts as "does not fit").
    Output:
        Solution (method "nearest_neighbor[<sequencing>,split=<bool>]",
        runtime in seconds). Raises ValueError for an unknown sequencing
        name, RuntimeError if some order fits no empty van.
    """
    # Step 0: a typo in the method name should fail now, not deep inside the loop.
    if sequencing not in METHODS:
        raise ValueError(f"unknown sequencing {sequencing!r}; choose from {sorted(METHODS)}")
    start = time.perf_counter()                            # stopwatch, for runtime_s at the end

    # --- One set of limits for everything -----------------------------------
    params = params or instance.params                     # no params given: use the data's own
    vehicle = vehicle or params.vehicle(DEFAULT_VEHICLE)   # no vehicle given: use the Van
    # Copy the instance with these params and this vehicle as the only type.
    # Why: route.py, sequencing and make_solution then all enforce the SAME
    # limits, even if the caller passed tighter ones.
    work = dataclasses.replace(
        instance, params=dataclasses.replace(params, vehicle_types=(vehicle,))
    )
    d = work.dist_mi                                       # distance matrix (miles)
    depot = work.depot_index                               # where every route starts
    where = work.orders["LocationIndex"]                   # where each order is delivered

    unserved = set(int(o) for o in work.orders.index)      # at the start, all 43 orders wait
    routes = []                                            # finished routes: (vehicle, stops, orders)

    # --- OUTER loop: each pass builds ONE route ------------------------------
    while unserved:                                        # until every order is served
        stops: list[int] = []                              # this route's stops, in visit order
        orders: list[int] = []                             # this route's orders
        current = depot                                    # a new van leaves the depot
        # --- MIDDLE loop: keep adding to this route until nothing fits ---------
        while True:
            # Locations that still have waiting orders, nearest to `current` first.
            # The key is a pair (distance, index): equal distances go to the lower index.
            open_locs = sorted({int(where[o]) for o in unserved},
                               key=lambda loc: (d[current, loc], loc))
            added = False                                  # did we add anything this round?
            # --- INNER loops: try the nearest location, then the next, ... ------
            for loc in open_locs:
                waiting = sorted(o for o in unserved if where[o] == loc)   # orders waiting here
                # THE SPLIT OPTION. A "batch" is the orders tried as one unit:
                #   together -> one batch holding ALL of this location's orders
                #               (all-or-nothing, so one van delivers the whole location)
                #   split    -> one batch PER order, tried in order-number order
                #               (each order that fits is taken; the rest wait for a later van)
                batches = [[o] for o in waiting] if split_orders else [waiting]
                for batch in batches:
                    # If this location is already on the route (split case), it is not
                    # a second stop: the van is already going there.
                    trial_stops = stops if loc in stops else stops + [loc]
                    # Exact search is only allowed up to max_exact_stops stops,
                    # so a bigger tentative route counts as "does not fit".
                    if sequencing == "exact" and len(trial_stops) > max_exact_stops:
                        continue                           # try the next batch
                    # THE FIT TEST: ask sequencing for a legal visiting order of the
                    # tentative route (current stops + this batch's stop and orders).
                    # sequencing, not this file, applies the four limits.
                    r = best_sequence(trial_stops, orders + batch, work, vehicle,
                                      method=sequencing, max_exact_stops=max_exact_stops)
                    if r.sequence is not None:             # a legal order exists: it fits
                        stops = list(r.sequence)           # keep the order sequencing chose
                        orders += batch                    # the van now carries these orders
                        unserved -= set(batch)             # ...so they are no longer waiting
                        # "Nearest" is measured from the location added last, even if
                        # sequencing reordered the route (see the tie-break rule above).
                        current = loc
                        added = True
                        break                              # leave the batch loop
                if added:
                    break                                  # leave the location loop; the middle
                                                           # loop restarts from the new position
            if not added:                                  # no location fits: this route is full
                break
        # Safety net: a route with no orders means even an EMPTY van can't take
        # the nearest order. Stop with a clear error rather than loop forever
        # or silently drop an order.
        if not orders:
            raise RuntimeError(f"orders {sorted(unserved)} fit no empty {vehicle.name}")
        routes.append((vehicle.name, stops, orders))       # route finished; start the next one

    # --- Package the result --------------------------------------------------
    runtime = time.perf_counter() - start                  # seconds the whole build took
    method = f"nearest_neighbor[{sequencing},split={split_orders}]"   # shows the options used
    # make_solution recomputes every route's numbers with route.py.
    return make_solution(routes, work, method=method, runtime_s=runtime)
