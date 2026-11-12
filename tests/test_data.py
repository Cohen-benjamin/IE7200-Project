"""Tests for params.py and data.py against the Monday CSV instance.

Expected literals (43 orders, 34 stops, 10,223 ft3, 1,324.7 min, 35x35) come
from the project brief; they live only in tests, never in library code.
Units: miles, minutes, ft3.
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from dispatch.data import load_instance

# Locate data/csv relative to THIS file (tests/test_data.py -> repo root -> data/csv)
# so the tests work no matter which folder pytest is launched from.
DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "csv"


# A fixture is a setup function pytest runs for tests that name it as an argument.
# scope="module": load the CSVs once and share the result across this file.
@pytest.fixture(scope="module")
def inst():
    """The loaded Monday instance (read-only, shared across tests)."""
    return load_instance(DATA_DIR)


# --- (a) recompute location aggregates and compare to locations.csv ---------

def _per_location(inst, column, how):
    """Aggregate an orders column by LocationIndex; depot/empty rows -> 0."""
    # Group the 43 orders by the location they go to, pick one column.
    grouped = inst.orders.groupby("LocationIndex")[column]
    # how="count" -> number of orders per location; otherwise sum of the column.
    series = grouped.count() if how == "count" else grouped.sum()
    # Locations with no orders (the depot) are missing from the groupby result;
    # reindex over ALL 35 locations and fill those with 0 so shapes match the CSV.
    return series.reindex(inst.locations.index, fill_value=0)


def test_order_count_matches_locations_csv(inst):
    # Count orders per location from the orders table (independent of the CSV's
    # OrderCount column), then compare to what locations.csv claims.
    recomputed = _per_location(inst, "Volume_ft3", "count")
    pd.testing.assert_series_equal(
        recomputed, inst.locations["OrderCount"],
        check_names=False,   # the two series have different names; ignore
        check_dtype=False,   # int64 vs int32 etc. doesn't matter here
    )


def test_total_volume_matches_locations_csv(inst):
    # Same idea for volume: sum of order volumes per location vs TotalVolume_ft3.
    recomputed = _per_location(inst, "Volume_ft3", "sum")
    pd.testing.assert_series_equal(
        recomputed, inst.locations["TotalVolume_ft3"],
        check_names=False, check_dtype=False,
    )


def test_distance_from_depot_matches_matrix_row(inst):
    # Row `depot_index` of the matrix = miles from depot to every location.
    # Picking columns by locations.index keeps the order aligned with the CSV.
    from_depot = inst.dist_mi[inst.depot_index, inst.locations.index]
    # allclose = equal within tiny floating-point error.
    np.testing.assert_allclose(from_depot, inst.locations["DistanceFromDepot_mi"])


def test_depot_row_is_empty(inst):
    # .loc[...] picks the depot's row by its LocationIndex label.
    depot = inst.locations.loc[inst.depot_index]
    assert depot["IsDepot"] == 1
    # The depot receives no deliveries and is 0 miles from itself.
    assert depot["OrderCount"] == 0 and depot["TotalVolume_ft3"] == 0
    assert depot["DistanceFromDepot_mi"] == 0


# --- (b) distance matrix structure ------------------------------------------

def test_matrix_shape(inst):
    # 34 stops + 1 depot = 35 rows and 35 columns.
    assert inst.dist_mi.shape == (35, 35)


def test_matrix_symmetric(inst):
    # .T is the transpose; symmetric means d(i,j) == d(j,i) for every pair.
    np.testing.assert_array_equal(inst.dist_mi, inst.dist_mi.T)


def test_matrix_zero_diagonal(inst):
    # np.diag pulls d(i,i); every location is 0 miles from itself.
    assert (np.diag(inst.dist_mi) == 0).all()


def test_matrix_is_not_metric(inst):
    """Documents that the triangle inequality FAILS: d(i,j) > d(i,k)+d(k,j)."""
    d = inst.dist_mi
    # Build every two-leg trip i -> k -> j by broadcasting:
    #   d[:, :, None]  has shape (i, k, 1)  -> distance i->k
    #   d[None, :, :]  has shape (1, k, j)  -> distance k->j
    #   their sum has shape (i, k, j) = cost of going i -> k -> j.
    # .min(axis=1) takes the best intermediate stop k, leaving shape (i, j).
    # (k = i or k = j is included; that equals the direct leg, so it's harmless.)
    detour = (d[:, :, None] + d[None, :, :]).min(axis=1)
    # If any direct leg is longer than the best detour, the matrix is non-metric.
    # 1e-9 guards against floating-point noise.
    assert (d > detour + 1e-9).any()


# --- (c) totals -------------------------------------------------------------

def test_order_and_stop_counts(inst):
    assert inst.n_orders == 43       # unit of coverage = order
    assert len(inst.stops) == 34     # stops = distinct delivery locations
    assert inst.depot_index not in inst.stops   # the depot is not a stop


def test_total_volume(inst):
    # Whole numbers in the data, so exact equality is safe here.
    assert inst.orders["Volume_ft3"].sum() == 10_223


def test_total_unload_minutes(inst):
    # CSV stores each order's time rounded to 2 dp; the brief quotes the total to
    # 1 dp (1324.7). Half of 0.1 = 0.05 covers the brief's rounding.
    assert inst.orders["UnloadTime_min"].sum() == pytest.approx(1324.7, abs=0.05)


def test_unload_time_recomputed_matches_csv(inst):
    van = inst.params.vehicle("Van")
    # Apply our own max(floor, rate*volume) rule to every order's volume...
    recomputed = inst.orders["Volume_ft3"].map(van.unload_time_min)
    # ...and compare to the CSV's value. Each CSV value is rounded to 2 dp, so it
    # can differ by up to 0.005 per order; 0.006 gives a small margin.
    np.testing.assert_allclose(recomputed, inst.orders["UnloadTime_min"], atol=0.006)


# --- orders_at --------------------------------------------------------------

def test_orders_at_partitions_orders(inst):
    # Flatten all the tuples into one list of order ids and sort it.
    flat = sorted(o for group in inst.orders_at.values() for o in group)
    # Every order must appear exactly once: no order lost, none duplicated.
    assert flat == list(inst.orders.index)


def test_orders_at_matches_order_locations(inst):
    for loc, group in inst.orders_at.items():
        # Values must be tuples (immutable), not lists.
        assert isinstance(group, tuple)
        # Each listed order really belongs to this location in the orders table.
        assert (inst.orders.loc[list(group), "LocationIndex"] == loc).all()


def test_stop_unload_is_per_order_not_per_stop_volume(inst):
    """Location 7 holds orders 3 and 41: 50.28 + 30 = 80.28, not f(total vol)."""
    van = inst.params.vehicle("Van")
    # Volumes of the orders delivered at stop 7.
    vols = [inst.orders.loc[o, "Volume_ft3"] for o in inst.orders_at[7]]
    # Correct rule: charge each order separately (floor applies per order)...
    per_order = sum(van.unload_time_min(v) for v in vols)
    assert per_order == pytest.approx(80.28, abs=0.01)
    # ...which is larger than wrongly applying the formula to the combined volume.
    assert per_order > van.unload_time_min(sum(vols))


# --- params -----------------------------------------------------------------

def test_params_values(inst):
    p = inst.params
    assert p.drive_min_per_mile == 1.5    # 60 / 40 mph
    assert p.max_drive_min == 660         # DOT driving cap, depot legs included
    assert p.max_duty_min == 840          # DOT drive + unload cap
    assert p.max_span_min == 600          # window 480 -> 1080


def test_van_vehicle_type(inst):
    van = inst.params.vehicle("Van")
    assert van.capacity_ft3 == 3200
    assert van.unload_time_min(157) == 30                    # below floor -> 30
    assert van.unload_time_min(1479) == pytest.approx(44.37)  # 0.03 * 1479
    # M1 is Van only, so asking for the Straight Truck must fail loudly.
    with pytest.raises(KeyError):
        inst.params.vehicle("Straight Truck")
