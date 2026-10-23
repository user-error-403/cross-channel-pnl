from datetime import date, timedelta
from itertools import pairwise

import pytest

from script.synth.clock import SimClock, load_as_of, save_as_of
from script.synth.config import Config


@pytest.fixture
def cfg() -> Config:
    return Config()


def test_from_config_defaults_to_start(cfg):
    clock = SimClock.from_config(cfg)
    assert clock.start == cfg.start_date
    assert clock.end == cfg.end_date
    assert clock.current == cfg.start_date


def test_from_config_accepts_explicit_as_of(cfg):
    as_of = cfg.start_date + timedelta(days=10)
    clock = SimClock.from_config(cfg, as_of=as_of)
    assert clock.current == as_of


@pytest.mark.parametrize("offset", [-1, 1])
def test_from_config_rejects_as_of_outside_window(cfg, offset):
    if offset < 0:
        as_of = cfg.start_date - timedelta(days=1)
    else:
        as_of = cfg.end_date + timedelta(days=1)

    with pytest.raises(ValueError, match="outside"):
        SimClock.from_config(cfg, as_of=as_of)


def test_rejects_start_after_end():
    with pytest.raises(ValueError, match="after end"):
        SimClock(
            start=date(2025, 1, 2),
            end=date(2025, 1, 1),
            current=date(2025, 1, 2),
        )


def test_advance_returns_new_clock(cfg):
    clock = SimClock.from_config(cfg)
    advanced = clock.advance()

    assert advanced is not clock
    assert clock.current == cfg.start_date
    assert advanced.current == cfg.start_date + timedelta(days=1)


def test_advance_adds_requested_days(cfg):
    clock = SimClock.from_config(cfg)
    assert clock.advance(3).current == cfg.start_date + timedelta(days=3)


@pytest.mark.parametrize("days", [0, -1])
def test_advance_rejects_non_positive_days(cfg, days):
    with pytest.raises(ValueError, match=">= 1"):
        SimClock.from_config(cfg).advance(days)


def test_advance_to_end_marks_finished(cfg):
    clock = SimClock.from_config(cfg, as_of=cfg.end_date - timedelta(days=1))
    assert not clock.finished

    clock = clock.advance()
    assert clock.finished
    assert clock.current == cfg.end_date


def test_advance_past_end_raises(cfg):
    with pytest.raises(ValueError, match="passes end"):
        SimClock.from_config(cfg, as_of=cfg.end_date).advance()


def test_advance_beyond_remaining_days_raises(cfg):
    clock = SimClock.from_config(cfg, as_of=cfg.end_date - timedelta(days=1))
    with pytest.raises(ValueError, match="passes end"):
        clock.advance(2)


def test_elapsed_is_exclusive(cfg):
    assert SimClock.from_config(cfg).elapsed == 0
    assert SimClock.from_config(cfg, as_of=cfg.end_date).elapsed == cfg.days - 1


def test_iter_days_covers_full_window(cfg):
    days = list(SimClock.from_config(cfg).iter_days())

    assert len(days) == cfg.days
    assert days[0] == cfg.start_date
    assert days[-1] == cfg.end_date
    assert len(set(days)) == len(days)
    assert days == sorted(days)
    assert all(b - a == timedelta(days=1) for a, b in pairwise(days))


def test_iter_days_independent_of_current(cfg):
    as_of = cfg.start_date + timedelta(days=30)
    assert list(SimClock.from_config(cfg, as_of=as_of).iter_days()) == list(
        SimClock.from_config(cfg).iter_days()
    )


def test_state_round_trip(tmp_path):
    path = tmp_path / "clock.state"
    value = date(2025, 6, 15)

    save_as_of(path, value)

    assert path.read_text(encoding="utf-8").strip() == value.isoformat()
    assert load_as_of(path, date(2000, 1, 1)) == value


def test_load_missing_file_returns_default(tmp_path):
    default = date(2025, 1, 1)
    assert load_as_of(tmp_path / "missing.state", default) == default


@pytest.mark.parametrize("content", ["", "2025-13-01"])
def test_load_corrupt_file_returns_default(tmp_path, content):
    path = tmp_path / "clock.state"
    path.write_text(content, encoding="utf-8")

    assert load_as_of(path, date(2025, 1, 1)) == date(2025, 1, 1)


def test_save_overwrites_existing_state(tmp_path):
    path = tmp_path / "clock.state"
    save_as_of(path, date(2025, 1, 1))
    save_as_of(path, date(2025, 1, 2))

    assert load_as_of(path, date(2000, 1, 1)) == date(2025, 1, 2)


def test_failed_replace_preserves_previous_state(tmp_path, monkeypatch):
    path = tmp_path / "clock.state"
    save_as_of(path, date(2025, 1, 1))

    def fail_replace(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr("script.synth.clock.os.replace", fail_replace)

    with pytest.raises(OSError, match="disk full"):
        save_as_of(path, date(2025, 1, 2))

    assert load_as_of(path, date(2000, 1, 1)) == date(2025, 1, 1)
    assert [entry.name for entry in tmp_path.iterdir()] == ["clock.state"]
