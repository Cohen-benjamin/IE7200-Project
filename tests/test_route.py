"""Tests for dispatch.route.route_metrics on the Monday instance.

Expected numbers are worked out from the CSVs (shown in comments); literals
live only in tests. Units: miles, minutes, ft3.
"""
from pathlib import Path

import pytest

from dispatch.ingest.data import load_instance
from dispatch.route import route_metrics

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "csv"


# A fixture builds a value once; tests receive it by naming it as an argument.
@pytest.fixture(scope="module")
def inst():
    """The loaded Monday instance."""
    return load_instance(DATA_DIR)


@pytest.fixture(scope="module")
def van(inst):
    """The Van vehicle type (M1 fleet)."""
    return inst.params.vehicle("Van")


def all_orders(inst, sequence):
    """Every order at the given locations (helper for whole-stop routes)."""
    # orders_at maps a location to its order numbers; this gathers them for every stop.
    return [o for s in sequence for o in inst.orders_at[s]]


# --- edge cases ------------------------------------------------------------

def test_empty_route_is_all_zero_and_feasible(inst, van):
    # A van that never leaves drives nothing, unloads nothing and breaks no limit.
    m = route_metrics([], [], inst, van)
    assert m.miles_total == 0 and m.drive_min == 0 and m.unload_min == 0
    assert m.span_min == 0 and m.volume_ft3 == 0
    assert m.slack_drive_min == inst.params.max_drive_min   # nothing used
    assert m.feasible


def test_single_stop_far_location(inst, van):
    # Location 14: 201 mi each way; orders 26 (160 ft3) and 42 (165 ft3).
    # Each number below is worked out by hand in the comment beside it.
    m = route_metrics([14], all_orders(inst, [14]), inst, van)
    assert m.miles_total == 402              # 201 + 201
    assert m.miles_interstop == 0            # one stop: no inter-stop leg
    assert m.drive_min == pytest.approx(603)     # 402 * 1.5
    assert m.slack_drive_min == pytest.approx(57)
    assert m.unload_min == pytest.approx(60)     # 30 + 30 (floor per order)
    assert m.span_min == pytest.approx(60)       # span = unload for one stop
    assert m.feasible


def test_multiple_orders_at_one_stop_unload_per_order(inst, van):
    # Location 7: order 3 (1676 ft3 -> 50.28) + order 41 (120 ft3 -> 30).
    # Unload time is paid per order: 50.28 + 30 = 80.28, not one rate on 1,796 ft3 (53.88).
    m = route_metrics([7], [3, 41], inst, van)
    assert m.unload_min == pytest.approx(80.28)
    assert m.unload_min != pytest.approx(van.unload_time_min(1796))  # not 53.88
    assert m.volume_ft3 == 1796


def test_split_stop_across_two_routes(inst, van):
    # Location 7's two orders on two different vans.
    # Splitting a location's orders across two vans must not lose or double-count anything.
    first = route_metrics([7], [41], inst, van)
    second = route_metrics([7], [3], inst, van)
    assert first.unload_min == pytest.approx(30)
    assert first.volume_ft3 == 120
    assert second.unload_min == pytest.approx(50.28)
    # Nothing double-counted: the two parts add up to the whole stop.
    whole = route_metrics([7], [3, 41], inst, van)
    assert first.unload_min + second.unload_min == pytest.approx(whole.unload_min)
    # Each van still drives the full round trip.
    assert first.miles_total == second.miles_total == whole.miles_total


def test_reversed_sequence_gives_same_metrics(inst, van):
    seq = [4, 7, 12]
    # Driving the same stops backwards costs the same, because the matrix is symmetric.
    forward = route_metrics(seq, all_orders(inst, seq), inst, van)
    backward = route_metrics(seq[::-1], all_orders(inst, seq), inst, van)
    assert forward == backward   # symmetric matrix -> identical route


def test_visit_order_changes_span(inst, van):
    d = inst.dist_mi
    # Same stops, same unloading, different visit order: only the inter-stop miles (and span) change.
    a = route_metrics([3, 13, 25], all_orders(inst, [3, 13, 25]), inst, van)
    b = route_metrics([13, 3, 25], all_orders(inst, [3, 13, 25]), inst, van)
    assert a.miles_interstop == d[3, 13] + d[13, 25]    # 227
    assert b.miles_interstop == d[13, 3] + d[3, 25]     # 154
    assert a.span_min != b.span_min
    assert a.unload_min == b.unload_min                 # same orders either way


def test_non_metric_leg_charged_as_given(inst, van):
    # d(25,32) = 98 mi although 25 -> 21 -> 32 is only 84 mi.
    # The matrix is not metric: a direct leg longer than a detour is still charged as given.
    m = route_metrics([25, 32], all_orders(inst, [25, 32]), inst, van)
    assert m.miles_interstop == 98


def test_infeasible_route_reports_negative_slack(inst, van):
    # 0 -> 14 -> 13 -> 0 = 201 + 211 + 71 = 483 mi -> 724.5 min > 660.
    # A too-long route must show a NEGATIVE slack and report not feasible.
    m = route_metrics([14, 13], all_orders(inst, [14, 13]), inst, van)
    assert m.miles_total == 483
    assert m.slack_drive_min == pytest.approx(-64.5)
    assert not m.feasible


def test_metrics_are_internally_consistent(inst, van):
    seq = [4, 7, 12]
    m = route_metrics(seq, all_orders(inst, seq), inst, van)
    # Re-derive each time from the miles and the rate: the reported fields must agree with each other.
    rate = inst.params.drive_min_per_mile
    assert m.drive_min == pytest.approx(m.miles_total * rate)
    assert m.duty_min == pytest.approx(m.drive_min + m.unload_min)
    assert m.span_min == pytest.approx(m.miles_interstop * rate + m.unload_min)


# --- invalid inputs ----------------------------------------------------------

# One test per (sequence, orders, reason) row: each is an invalid route that must be rejected.
@pytest.mark.parametrize("sequence, orders, why", [
    ([0, 4], [4, 10], "depot in sequence"),
    ([4, 4], [4, 10], "location visited twice"),
    ([4], [4, 4], "order listed twice"),
    ([99], [4], "unknown location"),
    ([4], [999], "unknown order"),
    ([4], [4, 3], "order 3 is at location 7, not visited"),
    ([4, 7], [4, 10], "stop 7 has no order on this route"),
])
def test_invalid_inputs_raise(inst, van, sequence, orders, why):
    # The test passes only if route_metrics raises ValueError.
    with pytest.raises(ValueError):
        route_metrics(sequence, orders, inst, van)
