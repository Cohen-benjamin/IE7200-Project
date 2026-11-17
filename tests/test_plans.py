"""Re-validate every route of real solver plans on the Monday instance.

For every plan a user can choose with run_selection.py by default (nearest neighbour and
Clarke-Wright, each with `nn` / `nn_2opt` sequencing and orders together / split: 8 plans;
the slow exact sequencing is not included) the plan is solved, saved to CSV, read back,
and checked three ways:
  (a) the independent validator finds no problem (4 limits + reported numbers),
  (b) every order 0..42 is delivered exactly once (coverage, counted here directly),
  (c) every route has room left (slack >= 0) on volume, drive, duty and span.
Units: miles, minutes, ft3.
"""
from pathlib import Path

import pandas as pd
import pytest

from dispatch.ingest.data import FILE_PREFIX, load_instance
from dispatch.ingest.params import load_params
from dispatch.solvers import clarke_wright, nearest_neighbor
from dispatch.validate import validate_plan

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "csv"

# The plans to check: (name shown in the test report, function instance -> Solution).
# The loops build the 8 default selections of run_selection.py (lam 1.0, Clarke-Wright re-sequencing on).
SOLVERS = []
for _seq in ("nn", "nn_2opt"):
    for _split in (False, True):
        _tag = f"{_seq}_{'split' if _split else 'together'}"
        # _seq=_seq, _split=_split bind THIS loop pass's values (otherwise every function would use the last ones).
        SOLVERS.append((f"nearest_neighbor_{_tag}",
                        lambda inst, _seq=_seq, _split=_split: nearest_neighbor.solve(
                            inst, sequencing=_seq, split_orders=_split)))
        SOLVERS.append((f"clarke_wright_{_tag}",
                        lambda inst, _seq=_seq, _split=_split: clarke_wright.solve(
                            inst, resequence=True, sequencing=_seq, split_orders=_split)))


# A fixture builds a value once and hands it to every test that names it; module = once per file.
@pytest.fixture(scope="module")
def inst():
    return load_instance(DATA_DIR)


@pytest.fixture(scope="module")
def params():
    """Limits read straight from the raw parameters CSV, as the validator expects."""
    return load_params(DATA_DIR / f"{FILE_PREFIX}_parameters.csv")


# parametrize = run the test once per solver; ids = the names shown in the report.
@pytest.mark.parametrize("solve", [s for _, s in SOLVERS], ids=[n for n, _ in SOLVERS])
def test_every_route_is_valid_and_every_order_delivered_once(solve, inst, params, tmp_path):
    sol = solve(inst)
    # Go through a real file, exactly as the plan would be handed in.
    sol.to_csv(tmp_path / "plan.csv", inst)
    plan = pd.read_csv(tmp_path / "plan.csv")

    # (a) The independent validator recomputes everything from raw data: no problems allowed.
    problems = validate_plan(plan, inst, params)
    assert problems == [], "\n".join(f"route {v.route_id}: [{v.check}] {v.detail}" for v in problems)

    # (b) Coverage: depot rows have no order (NaN), so dropna leaves only deliveries.
    delivered = sorted(plan["OrderIndex"].dropna().astype(int))
    assert delivered == sorted(inst.orders.index)          # each order once: none missing, none twice

    # (c) The four limits, route by route: slack = limit - usage must not be negative.
    for r in sol.routes:
        m = r.metrics
        assert m.slack_volume_ft3 >= 0, f"route {r.route_id} over capacity"
        assert m.slack_drive_min >= 0, f"route {r.route_id} over the drive limit"
        assert m.slack_duty_min >= 0, f"route {r.route_id} over the duty limit"
        assert m.slack_span_min >= 0, f"route {r.route_id} over the span limit"


def test_best_plan_has_the_reported_size(inst):
    # The best plan in the benchmark (results/benchmark.md): Clarke-Wright, lam 1.0, nn_2opt re-sequencing, orders together.
    # It is checked for validity by the test above; this pins the headline numbers that are reported.
    sol = clarke_wright.solve(inst, resequence=True, sequencing="nn_2opt")
    assert sol.n_routes == 5
    assert sol.total_miles == 1525
