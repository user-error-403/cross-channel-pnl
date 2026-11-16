from datetime import date, timedelta
from itertools import pairwise

import pytest

from script.synth.modules.clock import SimClock
from script.synth.modules.config import Config


@pytest.fixture
def cfg() -> Config:
    return Config()


def test_from_config_covers_config_window(cfg):
    clock = SimClock.from_config(cfg)

    # Fail if the clock opens anywhere but the configured inclusive window
    assert (clock.start, clock.end) == (cfg.start_date, cfg.end_date)


def test_rejects_start_after_end():
    # Fail if an inverted window constructs, giving an empty date range
    with pytest.raises(ValueError, match="after end"):
        SimClock(start=date(2025, 1, 2), end=date(2025, 1, 1))


def test_iter_days_covers_full_window(cfg):
    days = list(SimClock.from_config(cfg).iter_days())

    # Fail if a day is missing, duplicated, out of order, or non-contiguous
    assert len(days) == cfg.days
    assert days[0] == cfg.start_date
    assert days[-1] == cfg.end_date
    assert all(b - a == timedelta(days=1) for a, b in pairwise(days))
