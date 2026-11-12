"""Route metrics and feasibility for a given stop SEQUENCE.

This module evaluates ONE route whose visit order is already fixed.
Choosing the order is sequencing.py's job; validate.py checks plans
independently and must not import this module.

Units: miles, minutes, ft3.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from dispatch.data import Instance
from dispatch.params import VehicleType


@dataclass(frozen=True)
class RouteMetrics:
    """Everything measured about one route, plus slack on the four limits.

    A slack is "limit minus usage": positive = room left, negative = violated.

    Attributes:
        miles_total: depot -> first stop + inter-stop legs + last stop -> depot (mi).
        miles_interstop: stop-to-stop legs only, no depot legs (mi).
        drive_min: miles_total * drive_min_per_mile (min).
        unload_min: sum over the route's orders of max(floor, rate * volume) (min).
        duty_min: drive_min + unload_min (min).
        span_min: inter-stop driving (min) + unload_min. Depot legs excluded.
        volume_ft3: sum of the route's order volumes (ft3).
        slack_volume_ft3: vehicle capacity - volume_ft3 (ft3).
        slack_drive_min: max_drive_min - drive_min (min).
        slack_duty_min: max_duty_min - duty_min (min).
        slack_span_min: max_span_min - span_min (min).
    """

    miles_total: float
    miles_interstop: float
    drive_min: float
    unload_min: float
    duty_min: float
    span_min: float
    volume_ft3: float
    slack_volume_ft3: float
    slack_drive_min: float
    slack_duty_min: float
    slack_span_min: float

    @property
    def feasible(self) -> bool:
        """True if all four slacks are >= 0.

        Strict comparison, no tolerance (no hard-coded constants). A route that
        lands exactly on a limit could, through float rounding, show a slack of
        e.g. -1e-13 and be reported infeasible; the raw slacks make this visible.
        """
        return (
            self.slack_volume_ft3 >= 0
            and self.slack_drive_min >= 0
            and self.slack_duty_min >= 0
            and self.slack_span_min >= 0
        )


def _check_inputs(
    sequence: Sequence[int], orders_on_route: Sequence[int], instance: Instance
) -> None:
    """Reject inputs that do not describe a valid one-visit route.

    Inputs:
        sequence: LocationIndex values in visit order (depot not included).
        orders_on_route: OrderIndex values delivered by this route.
        instance: the problem instance.
    Output:
        None. Raises ValueError describing the first problem found.
    """
    depot = instance.depot_index
    # The depot is added automatically at both ends; inside the sequence it
    # would mean a mid-route return, which the model does not allow.
    if depot in sequence:
        raise ValueError(f"depot {depot} must not appear in sequence")
    # A set drops duplicates, so a shorter set means something repeated. 
    # Checks if sequence and orders on route have duplicates
    if len(set(sequence)) != len(sequence):
        raise ValueError(f"location visited twice in sequence {list(sequence)}")
    if len(set(orders_on_route)) != len(orders_on_route):
        raise ValueError(f"order listed twice in {list(orders_on_route)}")

    # Every location must be a real stop (one that has orders).
    # removes duplicates and checks that all location in sequence have orders
    unknown_locs = set(sequence) - set(instance.orders_at)
    if unknown_locs:
        raise ValueError(f"unknown or order-less locations: {sorted(unknown_locs)}")
    # Every order must exist in the orders table.
    unknown_orders = set(orders_on_route) - set(instance.orders.index)
    if unknown_orders:
        raise ValueError(f"unknown orders: {sorted(unknown_orders)}")

    # Where each order on this route is delivered by searching from instance for
    # orders on route @location index
    order_locs = set(instance.orders.loc[list(orders_on_route), "LocationIndex"])
    # An order whose location is not visited cannot be delivered by this van.
    not_visited = order_locs - set(sequence)
    if not_visited:
        raise ValueError(f"orders at locations not in sequence: {sorted(not_visited)}")
    # A visited location with none of its orders on this route is a wasted trip 
    # Checks empty stops (almost always a caller bug).
    empty_stops = set(sequence) - order_locs
    if empty_stops:
        raise ValueError(f"stops with no order on this route: {sorted(empty_stops)}")


def route_metrics(
    sequence: Sequence[int],
    orders_on_route: Sequence[int],
    instance: Instance,
    vehicle: VehicleType,
) -> RouteMetrics:
    """Measure one route: depot -> sequence[0] -> ... -> sequence[-1] -> depot.

    Inputs:
        sequence: LocationIndex values in visit order. The depot is implied at
            both ends and must NOT be included. Empty = van not dispatched.
        orders_on_route: OrderIndex values this van delivers. May be a subset
            of a location's orders (that location's orders split across vans).
        instance: problem instance; limits come from instance.params.
        vehicle: the VehicleType doing the route (capacity, unload rule).
    Output:
        RouteMetrics (miles, minutes, ft3) with slack on all four constraints.
        Raises ValueError for invalid input (see _check_inputs).
    Notes:
        Every leg is charged straight from the distance matrix in the direction
        of travel. The matrix is NOT metric; legs are never "shortened".
        Unload is paid per ORDER on this route, never per location.
    """
    _check_inputs(sequence, orders_on_route, instance)
    p = instance.params
    d = instance.dist_mi
    depot = instance.depot_index

    # --- Distance --------------------------------------------------------
    # len() > 0 rather than "if sequence:", because a numpy array of stops
    # would raise "truth value of an array is ambiguous" on the plain form.
    if len(sequence) > 0:
        # Full path with the depot added at both ends, e.g. [0, 4, 7, 0].
        path = [depot, *sequence, depot]
        # Sum each leg path[t] -> path[t+1], in travel direction.
        miles_total = sum(d[path[t], path[t + 1]] for t in range(len(path) - 1))
        # Only legs between consecutive stops (no depot legs). For one stop
        # range(0) is empty, so this is 0.
        miles_interstop = sum(
            d[sequence[t], sequence[t + 1]] for t in range(len(sequence) - 1)
        )
    else:
        # Empty route: the van never leaves, so no depot round trip is charged.
        miles_total = 0.0
        miles_interstop = 0.0

    # --- Load and unload (per order) -------------------------------------
    volumes = instance.orders.loc[list(orders_on_route), "Volume_ft3"]
    volume_ft3 = float(volumes.sum())
    # Floor applied to EACH order, then summed (never to the combined volume).
    unload_min = float(sum(vehicle.unload_time_min(v) for v in volumes))

    # --- Times -------------------------------------------------------------
    drive_min = float(miles_total) * p.drive_min_per_mile
    duty_min = drive_min + unload_min
    # Span = from first delivery to end of last: inter-stop driving + unloading.
    span_min = float(miles_interstop) * p.drive_min_per_mile + unload_min

    return RouteMetrics(
        miles_total=float(miles_total),
        miles_interstop=float(miles_interstop),
        drive_min=drive_min,
        unload_min=unload_min,
        duty_min=duty_min,
        span_min=span_min,
        volume_ft3=volume_ft3,
        slack_volume_ft3=vehicle.capacity_ft3 - volume_ft3,
        slack_drive_min=p.max_drive_min - drive_min,
        slack_duty_min=p.max_duty_min - duty_min,
        slack_span_min=p.max_span_min - span_min,
    )
