"""Volume-at-price profile from OHLCV candles.

METHODOLOGY (documented because it is an approximation, not tick TPO):

1. Bin size = ``tick_size * bin_multiple``. If the instrument tick size is
   unknown, fall back to a step ~ 0.05% of the mid price rounded to a 1/2/5
   figure, clamped so a profile has between ~20 and ~400 bins.

2. Each candle's volume is spread across the price bins its [low, high]
   range overlaps, weighted by how much of each bin the range covers
   (uniform-within-bar assumption). A doji (low == high) drops all its
   volume in the single containing bin. This is the standard way to derive
   a profile when only OHLC is available; it is exact only in the limit of
   1-tick bars.

3. POC (Point of Control) = bin with the greatest total volume.

4. Value area (default 70%): start from the POC bin, then repeatedly annex
   whichever neighbour - the bin just above the current top, or just below
   the current bottom - has more volume, until the annexed range holds
   >= ``value_area`` of total volume. VAH / VAL are the top / bottom edges
   of that range. This is the classic Market-Profile pairwise expansion.

5. HVN / LVN: a bin is a High/Low Volume Node when its volume is a local
   extremum vs the mean of the +/-``hvn_window`` bins around it - above
   ``hvn_ratio`` x local mean (HVN) or below ``lvn_ratio`` x (LVN). These
   thresholds are heuristics for visual structure, not statistical claims.

All figures inherit the caller's data tier (LIMITED for candle-derived).
"""

from __future__ import annotations

import math

from app.orderflow.types import Candle, DataTier, PriceLevel, VolumeProfile

_MIN_BINS = 20
_MAX_BINS = 400


def _auto_bin_size(lo: float, hi: float) -> float:
    span = max(hi - lo, 1e-9)
    raw = span / 120.0  # aim for ~120 bins
    if raw <= 0:
        return 0.05
    mag = 10.0 ** math.floor(math.log10(raw))
    for mult in (1.0, 2.0, 5.0, 10.0):
        if mult * mag >= raw:
            return round(mult * mag, 10)
    return round(10.0 * mag, 10)


def _clamp_bin_size(bin_size: float, lo: float, hi: float, *, allow_grow: bool) -> float:
    """Guard against a pathological number of levels. ``allow_grow`` widens
    tiny bins toward ``_MIN_BINS`` and only applies to auto-sizing - an
    explicit instrument tick size is always respected as the lower bound."""
    span = max(hi - lo, 1e-9)
    if span / bin_size > _MAX_BINS:
        bin_size = span / _MAX_BINS
    if allow_grow and span / bin_size < _MIN_BINS:
        bin_size = span / _MIN_BINS
    return bin_size


def _spread_bar_volume(
    buckets: dict[int, float], lo: float, hi: float, vol: float, bin_size: float, base: float
) -> None:
    """Add ``vol`` across bins covering [lo, hi], weighted by overlap."""
    if vol <= 0:
        return
    if hi <= lo:
        idx = int(math.floor((lo - base) / bin_size))
        buckets[idx] = buckets.get(idx, 0.0) + vol
        return
    first = int(math.floor((lo - base) / bin_size))
    last = int(math.floor((hi - base) / bin_size))
    total_range = hi - lo
    for idx in range(first, last + 1):
        bin_lo = base + idx * bin_size
        bin_hi = bin_lo + bin_size
        overlap = min(hi, bin_hi) - max(lo, bin_lo)
        if overlap <= 0:
            continue
        buckets[idx] = buckets.get(idx, 0.0) + vol * (overlap / total_range)


def build_volume_profile(
    candles: list[Candle],
    *,
    tick_size: float | None = None,
    bin_multiple: int = 1,
    value_area: float = 0.70,
    price_min: float | None = None,
    price_max: float | None = None,
    source_interval: str = "1m",
    hvn_window: int = 4,
    hvn_ratio: float = 1.35,
    lvn_ratio: float = 0.55,
    tier: DataTier = DataTier.LIMITED,
) -> VolumeProfile:
    rows = [c for c in candles if c.volume and c.volume > 0 and c.high >= c.low]
    if price_min is not None:
        rows = [c for c in rows if c.high >= price_min]
    if price_max is not None:
        rows = [c for c in rows if c.low <= price_max]

    va_pct = round(value_area * 100)
    method = (
        f"Volume-at-price by distributing each {source_interval} bar's volume "
        "across the prices it spanned (uniform-within-bar). POC = max-volume "
        f"bin; value area = {va_pct}% pairwise expansion from POC."
    )
    caveats = [
        "Approximation from OHLCV bars, not tick data - exact only for 1-tick bars.",
        "No trade side in the source, so bins carry volume but no delta.",
    ]

    if not rows:
        return VolumeProfile(
            bin_size=tick_size or 0.05, levels=[], poc_price=None, vah_price=None,
            val_price=None, value_area_pct=value_area, hvn_prices=[], lvn_prices=[],
            total_volume=0.0, bars_used=0, source_interval=source_interval,
            tier=tier, method=method, caveats=[*caveats, "No candles with volume in range."],
        )

    lo = price_min if price_min is not None else min(c.low for c in rows)
    hi = price_max if price_max is not None else max(c.high for c in rows)
    if hi <= lo:
        hi = lo + (tick_size or 0.05)

    explicit = bool(tick_size)
    bin_size = (tick_size * max(1, bin_multiple)) if tick_size else _auto_bin_size(lo, hi)
    bin_size = _clamp_bin_size(bin_size, lo, hi, allow_grow=not explicit)
    base = math.floor(lo / bin_size) * bin_size

    buckets: dict[int, float] = {}
    for c in rows:
        _spread_bar_volume(
            buckets, max(c.low, lo), min(c.high, hi), c.volume, bin_size, base
        )
    if not buckets:
        buckets[0] = sum(c.volume for c in rows)

    idx_lo, idx_hi = min(buckets), max(buckets)
    levels: list[PriceLevel] = []
    for idx in range(idx_lo, idx_hi + 1):
        # lower price edge of the bin - for tick-aligned bins this is an
        # actual tradeable price, which is how a POC / VAH / VAL is quoted.
        price = base + idx * bin_size
        levels.append(PriceLevel(price=price, volume=buckets.get(idx, 0.0)))

    total = sum(pl.volume for pl in levels)
    poc_i = max(range(len(levels)), key=lambda i: levels[i].volume)
    poc_price = levels[poc_i].price

    # --- value area: pairwise expansion from the POC ---
    lo_i = hi_i = poc_i
    acc = levels[poc_i].volume
    target = value_area * total if total > 0 else 0.0
    while acc < target and (lo_i > 0 or hi_i < len(levels) - 1):
        below = levels[lo_i - 1].volume if lo_i > 0 else -1.0
        above = levels[hi_i + 1].volume if hi_i < len(levels) - 1 else -1.0
        if above >= below:
            hi_i += 1
            acc += levels[hi_i].volume
        else:
            lo_i -= 1
            acc += levels[lo_i].volume
    val_price = levels[lo_i].price
    vah_price = levels[hi_i].price

    # --- HVN / LVN vs local mean ---
    hvn: list[float] = []
    lvn: list[float] = []
    n = len(levels)
    for i in range(n):
        j0, j1 = max(0, i - hvn_window), min(n, i + hvn_window + 1)
        neigh = [levels[k].volume for k in range(j0, j1) if k != i]
        local_mean = sum(neigh) / len(neigh) if neigh else 0.0
        v = levels[i].volume
        if local_mean <= 0:
            continue
        if v >= hvn_ratio * local_mean and v >= levels[max(0, i - 1)].volume and v >= levels[min(n - 1, i + 1)].volume:
            hvn.append(levels[i].price)
        elif v <= lvn_ratio * local_mean and v > 0:
            lvn.append(levels[i].price)

    return VolumeProfile(
        bin_size=round(bin_size, 10),
        levels=levels,
        poc_price=round(poc_price, 4),
        vah_price=round(vah_price, 4),
        val_price=round(val_price, 4),
        value_area_pct=value_area,
        hvn_prices=[round(p, 4) for p in hvn],
        lvn_prices=[round(p, 4) for p in lvn],
        total_volume=total,
        bars_used=len(rows),
        source_interval=source_interval,
        tier=tier,
        method=method,
        caveats=caveats,
    )
