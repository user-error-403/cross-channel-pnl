from decimal import ROUND_HALF_UP, Decimal
from .config import Config


def money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def to_decimal(value: str) -> Decimal:
    return Decimal(str(value))


def to_usd(amount: Decimal, currency: str, cfg: Config) -> Decimal:
    rate = Decimal(str(cfg.fx_rates[currency]))
    return money(amount * rate)


def to_local(usd: Decimal, currency: str, cfg: Config) -> Decimal:
    rate = Decimal(str(cfg.fx_rates[currency]))
    return money(usd / rate)


def wrong_currency(cfg: Config, channel: str) -> str | None:
    """Return a relabelled store channel's currency."""
    others = [ch for ch in sorted(cfg.store_channels) if ch != channel]
    if not others:
        return None

    return cfg.channel_currency[others[0]]
