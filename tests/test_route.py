"""Tests for dispatch.route.route_metrics on the Monday instance.

Expected numbers are worked out from the CSVs (shown in comments); literals
live only in tests. Units: miles, minutes, ft3.
"""
from pathlib import Path

import pytest

from dispatch.data import load_instance
from dispatch.route import route_metrics

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "csv"


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
    return [o for s in sequence for o in inst.orders_at[s]]


# --- hand-computed route (values supplied by the user) ---------------------

@pytest.mark.skip(reason="awaiting hand-computed values from the user")
def test_hand_computed_two_stop_route(inst, van):
    """depot -> 4 -> 7 -> depot, orders 4, 10, 3, 41.

    Inputs: d(0,4)=17, d(4,7)=2, d(7,0)=16 mi; volumes 85, 200, 1676, 120 ft3.
    Replace each None with the hand-computed value, then remove the skip.
    """
    m = route_metrics([4, 7], [4, 10, 3, 41], inst, van)
    expected = {
        "miles_total": None,
        "miles_interstop": None,
        "drive_min": None,
        "unload_min": None,
        "duty_min": None,
        "span_min": None,
        "volume_ft3": None,
        "slack_volume_ft3": None,
        "slack_drive_min": None,
        "slack_duty_min": None,
        "slack_span_min": None,
    }
    for field, value in expected.items():
        assert getattr(m, field) == pytest.approx(value), field


# --- edge cases ------------------------------------------------------------

def test_empty_route_is_all_zero_and_feasible(inst, van):
    m = route_metrics([], [], inst, van)
    assert m.miles_total == 0 and m.drive_min == 0 and m.unload_min == 0
    assert m.span_min == 0 and m.volume_ft3 == 0
    assert m.slack_drive_min == inst.params.max_drive_min   # nothing used
    assert m.feasible


def test_single_stop_far_location(inst, van):
    # Location 14: 201 mi each way; orders 26 (160 ft3) and 42 (165 ft3).
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
    m = route_metrics([7], [3, 41], inst, van)
    assert m.unload_min == pytest.approx(80.28)
    assert m.unload_min != pytest.approx(van.unload_time_min(1796))  # not 53.88
    assert m.volume_ft3 == 1796


def test_split_stop_across_two_routes(inst, van):
    # Location 7's two orders on two different vans.
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
    forward = route_metrics(seq, all_orders(inst, seq), inst, van)
    backward = route_metrics(seq[::-1], all_orders(inst, seq), inst, van)
    assert forward == backward   # symmetric matrix -> identical route


def test_visit_order_changes_span(inst, van):
    d = inst.dist_mi
    a = route_metrics([3, 13, 25], all_orders(inst, [3, 13, 25]), inst, van)
    b = route_metrics([13, 3, 25], all_orders(inst, [3, 13, 25]), inst, van)
    assert a.miles_interstop == d[3, 13] + d[13, 25]    # 227
    assert b.miles_interstop == d[13, 3] + d[3, 25]     # 154
    assert a.span_min != b.span_min
    assert a.unload_min == b.unload_min                 # same orders either way


def test_non_metric_leg_charged_as_given(inst, van):
    # d(25,32) = 98 mi although 25 -> 21 -> 32 is only 84 mi.
    m = route_metrics([25, 32], all_orders(inst, [25, 32]), inst, van)
    assert m.miles_interstop == 98


def test_infeasible_route_reports_negative_slack(inst, van):
    # 0 -> 14 -> 13 -> 0 = 201 + 211 + 71 = 483 mi -> 724.5 min > 660.
    m = route_metrics([14, 13], all_orders(inst, [14, 13]), inst, van)
    assert m.miles_total == 483
    assert m.slack_drive_min == pytest.approx(-64.5)
    assert not m.feasible


def test_metrics_are_internally_consistent(inst, van):
    seq = [4, 7, 12]
    m = route_metrics(seq, all_orders(inst, seq), inst, van)
    rate = inst.params.drive_min_per_mile
    assert m.drive_min == pytest.approx(m.miles_total * rate)
    assert m.duty_min == pytest.approx(m.drive_min + m.unload_min)
    assert m.span_min == pytest.approx(m.miles_interstop * rate + m.unload_min)


# --- invalid inputs ----------------------------------------------------------

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
    with pytest.raises(ValueError):
        route_metrics(sequence, orders, inst, van)
