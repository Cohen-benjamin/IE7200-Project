"""Tests for dispatch.audit on the Monday instance and a tiny hand-built matrix.

Expected numbers come from a hand check of the CSVs (see plan); they live only
in tests, never in library code. Units: miles, minutes, ft3.
"""
import dataclasses
from pathlib import Path

import numpy as np
import pytest

from dispatch import audit
from dispatch.data import load_instance

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "csv"


@pytest.fixture(scope="module")
def inst():
    """The loaded Monday instance."""
    return load_instance(DATA_DIR)


@pytest.fixture(scope="module")
def viol(inst):
    """Triangle violations of the Monday instance (computed once)."""
    return audit.triangle_violations(inst)


# --- audit reports, never modifies ----------------------------------------

def test_audit_does_not_modify_instance(inst):
    dist_before = inst.dist_mi.copy()
    orders_before = inst.orders.copy()
    locations_before = inst.locations.copy()
    # Run every audit function once.
    v = audit.triangle_violations(inst)
    audit.violation_location_counts(v)
    audit.location_profile(inst)
    audit.single_stop_feasibility(inst)
    audit.one_visit_checks(inst, v)
    # Everything is exactly as it was.
    np.testing.assert_array_equal(inst.dist_mi, dist_before)
    assert inst.orders.equals(orders_before)
    assert inst.locations.equals(locations_before)


# --- 1. triangle inequality --------------------------------------------------

def test_every_violation_row_is_a_real_violation(inst, viol):
    d = inst.dist_mi
    for r in viol.itertuples():
        assert r.i < r.j                         # each pair listed once
        assert len({r.i, r.j, r.k}) == 3         # three different locations
        assert d[r.i, r.j] > d[r.i, r.k] + d[r.k, r.j]   # recomputed from the matrix
        assert r.excess_mi == r.direct_mi - r.via_k_mi


def test_violation_count_and_worst(viol):
    assert len(viol) == 270
    worst = viol.iloc[0]
    assert (worst.i, worst.j, worst.k) == (25, 32, 21)
    assert worst.excess_mi == 14
    assert worst.excess_min == pytest.approx(21.0)   # 14 mi * 1.5 min/mi


def test_metric_matrix_has_no_violations(inst):
    # Three points on a line at 0, 3, 5 miles: a metric matrix by construction.
    d = np.array([[0, 3, 5], [3, 0, 2], [5, 2, 0]], dtype=float)
    tiny = dataclasses.replace(inst, dist_mi=d)   # copy of inst with only dist changed
    assert len(audit.triangle_violations(tiny)) == 0


def test_non_metric_matrix_is_detected(inst):
    # d(0,2) = 10 but 0 -> 1 -> 2 = 2: exactly one violation, excess 8.
    d = np.array([[0, 1, 10], [1, 0, 1], [10, 1, 0]], dtype=float)
    tiny = dataclasses.replace(inst, dist_mi=d)
    v = audit.triangle_violations(tiny)
    assert len(v) == 1
    assert (v.iloc[0].i, v.iloc[0].j, v.iloc[0].k, v.iloc[0].excess_mi) == (0, 2, 1, 8)


def test_location_counts_sum_to_violations(viol):
    counts = audit.violation_location_counts(viol)
    # Each violation has two endpoints and one shortcut.
    assert counts["as_endpoint"].sum() == 2 * len(viol)
    assert counts["as_shortcut"].sum() == len(viol)


# --- 2 & 3. per-location profile and single-stop feasibility -----------------

def test_profile_known_values(inst):
    prof = audit.location_profile(inst)
    assert len(prof) == 34
    assert prof.loc[14, "drive_slack_min"] == pytest.approx(57)       # 660 - 2*201*1.5
    assert prof.loc[7, "total_unload_min"] == pytest.approx(80.28)    # 50.28 + 30
    assert prof.loc[24, "total_unload_min"] == pytest.approx(90)      # 3 orders x 30
    assert prof["total_volume_ft3"].sum() == 10_223


def test_all_stops_feasible_alone(inst):
    feas = audit.single_stop_feasibility(inst)
    assert feas["feasible"].all()
    assert feas.loc[14, "binding"] == "drive_slack_min"
    assert feas.loc[14, "duty_slack_min"] == pytest.approx(177)       # 840 - (603 + 60)


# --- 4. one-visit checks ------------------------------------------------------

def test_one_visit_checks(inst, viol):
    findings = audit.one_visit_checks(inst, viol)
    status = {f.check[0]: f.status for f in findings}   # keyed by letter a..f
    assert status == {"a": "OK", "b": "OK", "c": "OK",
                      "d": "WARN", "e": "WARN", "f": "WARN"}
    # The depot must not be listed among the stops in check (e).
    e = next(f for f in findings if f.check.startswith("e."))
    assert "[0," not in e.detail
