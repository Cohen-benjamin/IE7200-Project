"""Run all solvers on the Monday instance and tabulate results."""
from __future__ import annotations

import time
from pathlib import Path

from dispatch.data import load_json
from dispatch.solvers import brute, clarke_wright, nearest_neighbor
from dispatch.validate import validate

DATA = Path(__file__).resolve().parents[1] / "data" / "ie7200_Mon.json"
SOLVERS = {"nearest_neighbor": nearest_neighbor, "clarke_wright": clarke_wright, "brute": brute}


def main() -> None:
    inst = load_json(DATA)
    for name, mod in SOLVERS.items():
        t0 = time.perf_counter()
        sol = mod.solve(inst)
        dt = time.perf_counter() - t0
        issues = validate(inst, sol)
        print(f"{name:18s} {dt:8.3f}s  valid={not issues}")


if __name__ == "__main__":
    main()
