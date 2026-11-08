"""Tests for CSV ingestion."""
from pathlib import Path

import pytest

from dispatch.data import load_csv_dir

CSV = Path(__file__).resolve().parents[1] / "data" / "csv"


@pytest.fixture(scope="module")
def inst():
    return load_csv_dir(CSV)


def test_shape(inst):
    assert len(inst.orders) == 43
    assert len(inst.dist) == 35 and all(len(r) == 35 for r in inst.dist)
    assert inst.depot == 0


def test_van_only_defaults(inst):
    p = inst.params
    assert [v.name for v in p.vehicle_types] == ["Van"]
    assert p.vehicle_types[0].capacity_ft3 == 3200
    assert p.min_vehicles == 4 and not p.enforce_eligibility


def test_volume_needs_four_vans(inst):
    cap = inst.params.vehicle_types[0].capacity_ft3
    assert inst.total_volume_ft3 == 10223
    assert -(-inst.total_volume_ft3 // cap) == 4


def test_ten_straight_truck_orders_flagged(inst):
    assert sum(o.requires_straight_truck for o in inst.orders) == 10


def test_travel_time(inst):
    assert inst.travel_min(0, 1) == pytest.approx(49 / 40 * 60)


def test_orders_group_by_location(inst):
    assert sum(len(inst.orders_at(i)) for i in range(35)) == 43
