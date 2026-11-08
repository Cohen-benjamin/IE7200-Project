"""Smoke test: package and all modules import."""
import importlib

import pytest

MODULES = [
    "dispatch.params", "dispatch.data", "dispatch.audit", "dispatch.route",
    "dispatch.sequencing", "dispatch.solution", "dispatch.validate",
    "dispatch.solvers.brute", "dispatch.solvers.nearest_neighbor",
    "dispatch.solvers.clarke_wright",
]


@pytest.mark.parametrize("name", MODULES)
def test_import(name):
    importlib.import_module(name)
