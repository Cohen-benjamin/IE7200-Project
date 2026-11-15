"""Re-validate every saved plan in outputs/ against raw data.

Each outputs/*.csv (format: see dispatch/validate.py) gets its own test.
Skips while outputs/ holds no plans.
"""
from pathlib import Path

import pandas as pd
import pytest

from dispatch.data import FILE_PREFIX, load_instance
from dispatch.params import load_params
from dispatch.validate import validate_plan

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "csv"
# Every saved plan CSV; sorted so the test order is the same on every run.
PLANS = sorted((ROOT / "outputs").glob("*.csv"))


# Skip (instead of fail) when there are no saved plans.
@pytest.mark.skipif(not PLANS, reason="no saved plans in outputs/ yet")
# parametrize = run the test below once per plan file; ids = the file names shown in the report.
@pytest.mark.parametrize("plan_path", PLANS, ids=[p.name for p in PLANS])
def test_saved_plan_is_valid(plan_path):
    # Load the raw data and limits, exactly as the validator expects them.
    inst = load_instance(DATA_DIR)
    params = load_params(DATA_DIR / f"{FILE_PREFIX}_parameters.csv")
    # Read the plan back from disk and check it; an empty list means the plan is valid.
    violations = validate_plan(pd.read_csv(plan_path), inst, params)
    # Fail with a readable list of problems (route, check, detail) if any were found.
    assert violations == [], "\n" + "\n".join(
        f"route {v.route_id}: [{v.check}] {v.detail}" for v in violations
    )
