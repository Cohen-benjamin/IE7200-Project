"""Solution object, reporting, and export."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Route:
    vehicle_type: str
    stops: list[str]


@dataclass
class Solution:
    routes: list[Route] = field(default_factory=list)
    solver: str = ""
    runtime_s: float = 0.0

    def summary(self) -> dict:
        raise NotImplementedError

    def to_csv(self, path: str | Path) -> None:
        raise NotImplementedError

    def to_json(self, path: str | Path) -> None:
        raise NotImplementedError
