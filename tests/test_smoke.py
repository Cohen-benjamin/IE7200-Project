"""Smoke test: the package installs and imports."""
import importlib

import pytest

import dispatch

# Every module name that must be importable (a typo or syntax error shows up here).
MODULES = [
    "params", "data", "audit", "route", "sequencing", "solution", "validate",
    "solvers", "solvers.brute", "solvers.nearest_neighbor", "solvers.clarke_wright",
]


# The package itself imports and has a description (its docstring).
def test_import_dispatch():
    assert dispatch.__doc__


# Run the test once per module name.
@pytest.mark.parametrize("name", MODULES)
def test_import_submodules(name):
    # import_module imports by text name; any error makes the test fail.
    importlib.import_module(f"dispatch.{name}")
