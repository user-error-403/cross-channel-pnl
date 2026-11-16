import random
from collections.abc import Iterator
from datetime import date, datetime, time, timezone
from decimal import Decimal

from .config import Config
from .money_utils import money, to_decimal
from .reference import SERVICE_FEE_CONFIG


def _months(start: date, end: date) -> Iterator[tuple[int, int]]:
    """Yield every `(year, month)` from `start` to `end`, both inclusive."""
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        yield year, month

        if month == 12:
            year, month = year + 1, 1
        else:
            month += 1


def _charge_date(cfg: Config, year: int, month: int, rule: dict) -> date | None:
    """Return the charge day when it lands inside the window, else `None`."""
    charge_date = date(year, month, rule["charge_day"])
    if cfg.start_date <= charge_date <= cfg.end_date:
        return charge_date

    return None


def _service_fee_row(
    cfg: Config,
    channel: str,
    fee_type: str,
    rule: dict,
    charge_date: date,
    rng: random.Random,
) -> dict:
    """Assemble one monthly account-level fee row with no order keys."""
    low, high = (int(to_decimal(value) * 100) for value in rule["amount_range"])
    amount = money(Decimal(rng.randint(low, high)) / 100)
    charged_at = datetime.combine(charge_date, time.min, tzinfo=timezone.utc)

    return {
        "service_fee_id": (
            f"svc_{channel}_{fee_type}_{charge_date.year:04d}"
            f"_{charge_date.month:02d}"
        ),
        "channel": channel,
        "fee_type": fee_type,
        "source_fee_type": rule["source_fee_type"],
        "amount": amount,
        "currency": cfg.channel_currency[channel],
        "charged_at": charged_at,
        "updated_at": charged_at,
    }


# ------------------------------------------------------------
# GENERATE SERVICE FEES
# ------------------------------------------------------------


def generate_service_fees(cfg: Config) -> list[dict]:
    """
    Return one account-level fee row per channel, fee type, and month.

    `SERVICE_FEE_CONFIG` fees post per account with no order reference,
    so each row stands apart from the order stream. Each pass seeds its own
    `random.Random` from `cfg.seed`, the channel, the fee type, and the
    year-month, so one month cannot shift another.

    Expectations:
    - Each `SERVICE_FEE_CONFIG` channel is keyed in `cfg.channel_currency`,
      because the row reads that channel's currency.
    - A charge day outside the window drops that one row and does not clamp to
      the nearest day.

    Returns:
    - Rows come out ordered by month, then channel name, then fee type name.
    - A single-value `amount_range` repeats its one amount every month,
      e.g. amazon subscription.
    """
    fees: list[dict] = []
    for year, month in _months(cfg.start_date, cfg.end_date):
        for channel in sorted(SERVICE_FEE_CONFIG):
            for fee_type in sorted(SERVICE_FEE_CONFIG[channel]):
                rule = SERVICE_FEE_CONFIG[channel][fee_type]
                charge_date = _charge_date(cfg, year, month, rule)
                if charge_date is None:
                    continue

                rng = random.Random(
                    f"{cfg.seed}:service_fees:{channel}:{fee_type}"
                    f":{year:04d}-{month:02d}"
                )
                fees.append(
                    _service_fee_row(
                        cfg=cfg,
                        channel=channel,
                        fee_type=fee_type,
                        rule=rule,
                        charge_date=charge_date,
                        rng=rng,
                    )
                )

    return fees
