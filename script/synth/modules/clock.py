from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta

from .config import Config


@dataclass(frozen=True)
class SimClock:
    """
    Immutable simulated calendar window.

    - Window Bounds: `start` and `end` are both inclusive.
    """

    start: date
    end: date

    def __post_init__(self) -> None:
        if self.start > self.end:
            raise ValueError(f"start {self.start} is after end {self.end}")

    @classmethod
    def from_config(cls, cfg: Config) -> SimClock:
        """Build a clock that covers the `Config` window."""
        return cls(start=cfg.start_date, end=cfg.end_date)

    def iter_days(self) -> Iterator[date]:
        """Yield every date from `start` to `end`, both inclusive."""
        day = self.start
        while day <= self.end:
            yield day
            day += timedelta(days=1)
