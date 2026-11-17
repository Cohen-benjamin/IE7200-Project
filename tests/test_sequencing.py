"""Tests for dispatch.sequencing.

Part 1 uses a tiny SYNTHETIC instance where the minimum-mile order breaks
span but another order is feasible. Part 2 uses the Monday data.
Units: miles, minutes, ft3.
"""
import itertools
import random
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from dispatch.ingest.data import Instance, load_instance
from dispatch.ingest.params import Params, VehicleType
from dispatch.route import route_metrics
from dispatch.sequencing import (
    METHODS, best_sequence, exact_sequence, nn_2opt_sequence, nn_sequence,
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "csv"


# --- Part 1: synthetic instance ------------------------------------------------
#
# Depot 0, stops 1, 2, 3, one 100-ft3 order each (unload 30 each = 90 min).
# d(0,1)=1 d(0,2)=1 d(0,3)=10 d(1,2)=2 d(1,3)=6 d(2,3)=6   (non-metric on purpose)
#
#   order   total mi  inter mi  span = inter*1.5 + 90   feasible if span <= 105
#   1-3-2     14        12        108                   NO  (cheapest, breaks span)
#   1-2-3     19         8        102                   yes
#   2-1-3     19         8        102                   yes

def make_synthetic(window_end_min: float) -> Instance:
    """Tiny 3-stop instance; window 0..window_end_min sets the span limit."""
    van = VehicleType("Van", capacity_ft3=3200, unload_min_per_ft3=0.03, min_unload_min=30)
    params = Params(
        drive_min_per_mile=1.5, max_drive_min=660, max_duty_min=840,
        window_start_min=0, window_end_min=window_end_min, vehicle_types=(van,),
    )
    d = np.array([
        [0, 1, 1, 10],
        [1, 0, 2, 6],
        [1, 2, 0, 6],
        [10, 6, 6, 0],
    ], dtype=float)
    # Orders 0, 1, 2 delivered at locations 1, 2, 3.
    orders = pd.DataFrame(
        {"LocationIndex": [1, 2, 3], "Volume_ft3": [100, 100, 100]},
        index=pd.Index([0, 1, 2], name="OrderIndex"),
    )
    locations = pd.DataFrame(index=pd.Index([0, 1, 2, 3], name="LocationIndex"))
    return Instance(
        params=params, dist_mi=d, depot_index=0, orders=orders,
        locations=locations, orders_at={1: (0,), 2: (1,), 3: (2,)},
    )


@pytest.fixture
def syn():
    return make_synthetic(window_end_min=105)


def test_synthetic_min_mile_order_breaks_span(syn):
    # Guard on the test data itself: the cheapest order really is infeasible.
    van = syn.params.vehicle("Van")
    m = route_metrics([1, 3, 2], [0, 1, 2], syn, van)
    assert m.miles_total == 14
    assert m.span_min == pytest.approx(108)
    assert not m.feasible


def test_exact_finds_feasible_non_minimum_order(syn):
    van = syn.params.vehicle("Van")
    # Read by field name: the result has several fields, so positional unpacking would be fragile.
    r = exact_sequence([1, 2, 3], [0, 1, 2], syn, van)
    assert r.sequence == (1, 2, 3)   # 1-2-3 and 2-1-3 tie; lower tuple wins
    assert r.metrics.miles_total == 19
    assert r.metrics.span_min == pytest.approx(102)
    assert r.metrics.feasible
    assert r.method_used == "exact" and r.proven


def test_exact_proves_infeasible(syn):
    # Span limit 100: even the best span (102) fails, so no order works.
    tight = make_synthetic(window_end_min=100)
    van = tight.params.vehicle("Van")
    r = exact_sequence([1, 2, 3], [0, 1, 2], tight, van)
    assert r.sequence is None
    assert r.proven is True
    assert r.metrics.miles_interstop == 8      # closest attempt reported
    assert r.metrics.slack_span_min == pytest.approx(-2)


# --- Part 2: Monday data --------------------------------------------------------

@pytest.fixture(scope="module")
def inst():
    return load_instance(DATA_DIR)


@pytest.fixture(scope="module")
def van(inst):
    return inst.params.vehicle("Van")


def all_orders(inst, stops):
    """Every order at the given stops."""
    # Gather every order number at the given stops.
    return [o for s in stops for o in inst.orders_at[s]]


def brute_force(stops, inst, van):
    """Reference answer: route_metrics on EVERY order, cheapest feasible."""
    # Slow but obviously correct: try every order and let route.py judge each one.
    feasible = []
    for perm in itertools.permutations(stops):
        m = route_metrics(perm, all_orders(inst, stops), inst, van)
        if m.feasible:
            feasible.append(m.miles_total)
    return min(feasible) if feasible else None  # None = no order is legal


# No stops: the answer is an empty route, and it counts as proven.
def test_empty_set(inst, van):
    r = exact_sequence([], [], inst, van)
    assert r.sequence == () and r.metrics.miles_total == 0 and r.proven


# One stop has only one order; 402 miles x 1.5 = 603 drive minutes.
def test_single_stop(inst, van):
    r = exact_sequence([14], all_orders(inst, [14]), inst, van)
    assert r.sequence == (14,)
    assert r.metrics.drive_min == pytest.approx(603)


# exact must match the brute-force answer on three different stop sets.
@pytest.mark.parametrize("stops", [[1, 2, 3, 4, 5], [25, 1, 2, 3, 4], [14, 3, 4]])
def test_exact_matches_brute_force(inst, van, stops):
    r = exact_sequence(stops, all_orders(inst, stops), inst, van)
    expected = brute_force(stops, inst, van)
    if expected is None:
        assert r.sequence is None
    else:
        assert r.metrics.miles_total == pytest.approx(expected)


def test_exact_never_worse_than_nn_2opt(inst, van):
    # The exact search can never be worse than the heuristic (rung 1, nn_2opt).
    rng = random.Random(0)  # fixed seed: the same 25 random sets on every run
    for _ in range(25):
        stops = rng.sample(list(inst.stops), rng.randint(2, 6))
        orders = all_orders(inst, stops)
        ex = exact_sequence(stops, orders, inst, van)
        he = nn_2opt_sequence(stops, orders, inst, van)
        # Compare only when the heuristic found a legal order.
        if he.sequence is not None:
            # 2-opt found a feasible order, so exact must too, no worse.
            assert ex.sequence is not None
            assert ex.metrics.miles_total <= he.metrics.miles_total + 1e-9


@pytest.mark.parametrize("name", sorted(METHODS))
def test_best_sequence_runs_the_named_method(inst, van, name):
    # best_sequence must run exactly the method it is told to, with no automatic switching.
    stops = [1, 2, 3, 4]
    orders = all_orders(inst, stops)
    # Going through best_sequence must give exactly the same result as calling the method directly.
    via_dispatch = best_sequence(stops, orders, inst, van, method=name)
    direct = METHODS[name](stops, orders, inst, van)
    assert via_dispatch == direct


def test_best_sequence_requires_method(inst, van):
    # method has no default, so leaving it out must fail.
    with pytest.raises(TypeError):          # required argument missing
        best_sequence([1, 2], all_orders(inst, [1, 2]), inst, van)


def test_best_sequence_exact_respects_size_limit(inst, van):
    # The default cap is 10 stops: an 11-stop set is refused before any search starts.
    eleven = list(inst.stops[:11])
    with pytest.raises(ValueError):
        best_sequence(eleven, all_orders(inst, eleven), inst, van, method="exact")
    # A 9-stop set is refused when the cap is lowered below its size, and solved when it is not.
    big = [25, 1, 2, 12, 11, 9, 8, 5, 10]          # 9 stops
    with pytest.raises(ValueError):
        best_sequence(big, all_orders(inst, big), inst, van, method="exact", max_exact_stops=8)
    r = best_sequence(big, all_orders(inst, big), inst, van, method="exact",
                      max_exact_stops=9)
    assert r.proven is True


def test_nn_2opt_serves_the_long_span_bound_route(inst, van):
    """A 12-stop set with one legal order that is hard to find.

    A legal order exists (span 594 of 600 as listed). Plain nn fails on it, but
    span-aware 2-opt repairs the nn tour into a legal one.
    """
    stops = [25, 1, 2, 12, 11, 9, 8, 5, 10, 6, 4, 3]
    orders = all_orders(inst, stops)
    legal = route_metrics(stops, orders, inst, van)
    assert legal.feasible                                   # a legal order exists
    assert nn_sequence(stops, orders, inst, van).sequence is None
    r = nn_2opt_sequence(stops, orders, inst, van)
    assert r.sequence is not None and r.metrics.feasible    # span-aware 2-opt found one
    assert sorted(r.sequence) == sorted(stops)


def test_too_many_stops_for_exact(inst, van):
    # The first 11 stops: more than the default cap of 10.
    stops = list(inst.stops[:11])
    with pytest.raises(ValueError):
        exact_sequence(stops, all_orders(inst, stops), inst, van)


def test_split_orders_passed_through(inst, van):
    # Only order 41 of location 7's two orders rides on this van.
    # Only order 41 of location 7 is on this van: volume 120 + 85 + 200, unload 30 + 30 + 30.
    r = exact_sequence([7, 4], [41, 4, 10], inst, van)
    assert r.metrics.volume_ft3 == 120 + 85 + 200
    assert r.metrics.unload_min == pytest.approx(90)


# --- Part 3: the method ladder ------------------------------------------------

def test_ladder_story_on_synthetic(syn):
    """Each rung, on the instance where the cheapest tour breaks span."""
    van = syn.params.vehicle("Van")
    # The same inputs are reused for all three methods.
    args = ([1, 2, 3], [0, 1, 2], syn, van)
    # Rung 0: nearest neighbour happens to pick 1-2-3, which is feasible.
    r0 = nn_sequence(*args)
    assert r0.sequence == (1, 2, 3) and r0.metrics.miles_total == 19
    # Rung 1: 2-opt is span-aware. Plain miles would choose 1-3-2 (14 miles), which
    # breaks span, so it keeps the legal 1-2-3.
    r1 = nn_2opt_sequence(*args)
    assert r1.sequence == (1, 2, 3)
    assert r1.metrics.miles_total == 19 and r1.metrics.feasible
    # Reference: exact proves 19 miles is the best feasible.
    assert exact_sequence(*args).metrics.miles_total == 19


def test_exact_effort_counts_on_synthetic(syn):
    van = syn.params.vehicle("Van")
    r = exact_sequence([1, 2, 3], [0, 1, 2], syn, van)
    assert r.orders_scored == 3     # 3!/2 = 3 orders (mirror images skipped)
    assert r.evaluations == 2       # 1-3-2 checked and fails, then 1-2-3 passes


def test_two_opt_never_worse_than_nn(inst, van):
    # Try every stop as a starting point.
    for seed in inst.stops:
        # The stop plus its 4 nearest stops: a route-like set.
        near = sorted(inst.stops, key=lambda s: (inst.dist_mi[seed, s], s))[:5]
        orders = all_orders(inst, near)
        a = nn_sequence(near, orders, inst, van)
        b = nn_2opt_sequence(near, orders, inst, van)
        # If nn's tour already meets span, 2-opt only saves miles. If it does not, 2-opt may spend
        # extra miles to cut the span excess, so the miles comparison would not be fair.
        if a.metrics.slack_span_min >= 0:
            assert b.metrics.miles_total <= a.metrics.miles_total


@pytest.mark.parametrize("name", sorted(METHODS))
def test_every_rung_returns_a_permutation(inst, van, name):
    # A route must contain each of its stops exactly once: sorted(result) == the stop list.
    stops = [1, 2, 3, 4, 5]
    r = best_sequence(stops, all_orders(inst, stops), inst, van, method=name)
    if r.sequence is not None:
        assert sorted(r.sequence) == stops
    assert r.evaluations >= 1


def test_best_sequence_unknown_method(inst, van):
    # A misspelt method name must fail loudly.
    with pytest.raises(ValueError):
        best_sequence([1, 2], all_orders(inst, [1, 2]), inst, van, method="magic")


def test_two_opt_never_adds_span_excess(inst, van):
    # Span-aware 2-opt: the span excess (minutes over the limit) of its tour is never more than the
    # nearest-neighbour tour it started from. Random stop sets, fixed seed.
    rng = random.Random(1)
    for _ in range(40):
        stops = rng.sample(list(inst.stops), rng.randint(3, 9))
        orders = all_orders(inst, stops)
        start = nn_sequence(stops, orders, inst, van).metrics
        after = nn_2opt_sequence(stops, orders, inst, van).metrics
        assert max(0.0, -after.slack_span_min) <= max(0.0, -start.slack_span_min) + 1e-9
