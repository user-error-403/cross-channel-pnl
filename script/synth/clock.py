from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import date, timedelta
from pathlib import Path

from .config import Config


@dataclass(frozen=True)
class SimClock:
    """
    Immutable simulated calendar window with a current day.

    - Window Bounds: `start` and `end` are both inclusive, and `current` never
      leaves that range.
    """

    start: date
    end: date
    current: date

    def __post_init__(self) -> None:
        if self.start > self.end:
            raise ValueError(f"start {self.start} is after end {self.end}")
        if not self.start <= self.current <= self.end:
            raise ValueError(
                f"current {self.current} outside [{self.start}, {self.end}]"
            )

    @classmethod
    def from_config(cls, cfg: Config, as_of: date | None = None) -> SimClock:
        """
        Build a clock covering the `Config` window, starting at `cfg.start_date` when `as_of` is `None`.
        """
        return cls(
            start=cfg.start_date,
            end=cfg.end_date,
            current=as_of or cfg.start_date,
        )

    @property
    def finished(self) -> bool:
        """Return `True` when `current` is the final day of the window."""
        return self.current == self.end

    @property
    def elapsed(self) -> int:
        """Return whole days since `start`; the first day is 0 (exclusive count)."""
        return (self.current - self.start).days

    def advance(self, days: int = 1) -> SimClock:
        """
        Return a new clock advanced by `days`, never past `end`.
        """
        if days < 1:
            raise ValueError(f"days must be >= 1, got {days}")

        next_day = self.current + timedelta(days=days)
        if next_day > self.end:
            raise ValueError(
                f"cannot advance {days} day(s) from {self.current}: "
                f"passes end {self.end}"
            )

        return replace(self, current=next_day)

    def iter_days(self) -> Iterator[date]:
        """
        Yield every date in the window from `start` to `end`, both inclusive.

        - Determinism: A partially advanced clock yields the same dates as a
          fresh one, so iteration covers the full window.
        """
        day = self.start
        while day <= self.end:
            yield day
            day += timedelta(days=1)


def load_as_of(path: Path, default: date) -> date:
    """
    Read the persisted current day, falling back to `default` on any read or parse error.

    Args:
        path: File holding one ISO 8601 date, with optional surrounding whitespace.
        default: Date returned when the file is missing, unreadable, or malformed.

    Returns:
        The persisted date, or `default`.
    """
    try:
        raw = Path(path).read_text(encoding="utf-8").strip()
        return date.fromisoformat(raw)
    except (OSError, ValueError):
        return default


def save_as_of(path: Path, value: date) -> None:
    """
    Persist the current day as one ISO date, replacing any previous file.

    Args:
        path: Destination file; its parent directory must already exist.
        value: Date written as `value.isoformat()` plus a trailing newline.

    Behavior:
    - Atomicity: Readers never observe a partial file, and the temp file is
      removed when the write fails.
    """
    path = Path(path)

    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            tmp_path = Path(handle.name)
            handle.write(f"{value.isoformat()}\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
        raise
