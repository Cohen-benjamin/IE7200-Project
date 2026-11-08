"""Ingestion: raw JSON/CSV -> Instance object."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .params import Params


@dataclass
class Instance:
    """Normalized problem instance consumed by all solvers."""
    params: Params
    stops: dict          # stop_id -> attributes (demand, time window, coords, ...)
    dist: dict           # (i, j) -> distance
    time: dict           # (i, j) -> travel time


def load_json(path: str | Path) -> Instance:
    """Load an instance from ie7200_Mon.json."""
    raw = json.loads(Path(path).read_text())
    raise NotImplementedError("Map raw JSON schema to Instance")


def load_csv_dir(path: str | Path) -> Instance:
    """Load an instance from data/csv/*.csv."""
    raise NotImplementedError
