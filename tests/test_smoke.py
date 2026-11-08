"""Smoke test: the package installs and imports."""
import importlib

import pytest

import dispatch

MODULES = [
    "params", "data", "audit", "route", "sequencing", "solution", "validate",
    "solvers", "solvers.brute", "solvers.nearest_neighbor", "solvers.clarke_wright",
]


def test_import_dispatch():
    assert dispatch.__doc__


@pytest.mark.parametrize("name", MODULES)
def test_import_submodules(name):
    importlib.import_module(f"dispatch.{name}")
