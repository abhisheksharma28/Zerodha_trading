"""Build the tradable universe the scanner sweeps, in two tiers.

* **core**  - deep scan every cycle (daily + 15-minute candles + structure):
  the cash / index / commodity leg of every F&O root, capped and ordered
  by a cheap liquidity proxy so the historical-data budget (Kite allows
  ~3 history req/s) is spent where it matters.
* **broad** - shallow screen every cycle from one batched quote call:
  the rest of the active NSE equity list. A name is only promoted to a
  full evaluation if the quick screen flags it.

Everything comes from the canonical ``instruments`` master (synced from
Kite's dumps) - no hand-maintained symbol lists.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.instrument import Instrument

# NSE lists bonds, SGBs, govt securities, rights and partly-paid lines on the
# same EQ segment as ordinary shares. Screen the obvious non-equity out of the
# broad tier so the quote budget is not wasted on illiquid debt.
_NON_EQUITY = re.compile(
    r"^\d"                     # bonds start with a digit  (0ABCL31-N0)
    r"|-N[0-9A-Z]$"            # -N0 .. -NZ  debt series
    r"|-Y\d$|-Z\d$|-GB$|-GS$"  # more debt / gilt series
    r"|-RE$|-PP$|-RR$|-BL$"    # rights / partly-paid
    r"|^SGB|^GOI|GS\d{4}",     # sovereign gold bonds, govt securities
)


def _looks_like_equity(tradingsymbol: str) -> bool:
    return not _NON_EQUITY.search(tradingsymbol.strip().upper())

# Index roots that trade as an index (no cash equity row of their own).
_INDEX_ROOTS = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50", "SENSEX", "BANKEX"}
_INDEX_SYMBOL = {
    "NIFTY": "NIFTY 50", "BANKNIFTY": "NIFTY BANK", "FINNIFTY": "NIFTY FIN SERVICE",
    "MIDCPNIFTY": "NIFTY MIDCAP SELECT", "NIFTYNXT50": "NIFTY NEXT 50",
    "SENSEX": "SENSEX", "BANKEX": "BANKEX",
}


@dataclass(frozen=True)
class ScanInstrument:
    exchange: str
    tradingsymbol: str
    instrument_token: str
    segment: str
    name: str | None
    asset_class: str  # EQUITY | INDEX | COMMODITY
    has_options: bool
    underlying: str | None  # F&O root for the option overlay
    lot_size: int | None

    @property
    def ref(self) -> str:
        return f"{self.exchange}:{self.tradingsymbol}"


@dataclass
class Universe:
    core: list[ScanInstrument]
    broad: list[ScanInstrument]
    generated_at_day: str

    @property
    def all(self) -> list[ScanInstrument]:
        return [*self.core, *self.broad]

    @property
    def size(self) -> int:
        return len(self.core) + len(self.broad)


def _fno_roots(db: Session, exchange: str) -> set[str]:
    rows = db.execute(
        select(Instrument.underlying)
        .where(Instrument.exchange == exchange, Instrument.active.is_(True))
        .where(Instrument.underlying.is_not(None))
        .distinct()
    ).scalars().all()
    return {r.strip().upper() for r in rows if r}


def _cash_equities(db: Session) -> dict[str, Instrument]:
    rows = db.execute(
        select(Instrument).where(
            Instrument.exchange == "NSE",
            Instrument.instrument_type == "EQ",
            Instrument.segment == "NSE",
            Instrument.active.is_(True),
        )
    ).scalars().all()
    return {
        r.tradingsymbol.strip().upper(): r
        for r in rows
        if _looks_like_equity(r.tradingsymbol)
    }


def _indices(db: Session) -> dict[str, Instrument]:
    rows = db.execute(
        select(Instrument).where(
            Instrument.segment.in_(("INDICES", "NSE-INDICES", "BSE-INDICES")),
            Instrument.active.is_(True),
        )
    ).scalars().all()
    return {r.tradingsymbol.strip().upper(): r for r in rows}


def _near_month_commodity_futs(db: Session) -> dict[str, Instrument]:
    """One MCX future per root - the nearest non-expired monthly."""
    today = date.today()
    rows = db.execute(
        select(Instrument).where(
            Instrument.exchange == "MCX",
            Instrument.instrument_type == "FUT",
            Instrument.active.is_(True),
            Instrument.expiry.is_not(None),
            Instrument.expiry >= today,
        ).order_by(Instrument.expiry)
    ).scalars().all()
    out: dict[str, Instrument] = {}
    for r in rows:
        root = (r.underlying or r.name or r.tradingsymbol).strip().upper()
        out.setdefault(root, r)  # first = nearest expiry
    return out


def build(db: Session, *, core_max: int = 170, broad_max: int = 600) -> Universe:
    nfo_roots = _fno_roots(db, "NFO")
    mcx_roots = _fno_roots(db, "MCX")
    cash = _cash_equities(db)
    idx = _indices(db)
    commod = _near_month_commodity_futs(db)

    core: list[ScanInstrument] = []
    used: set[str] = set()

    # 1. indices with listed options
    for root in sorted(nfo_roots & _INDEX_ROOTS):
        sym = _INDEX_SYMBOL.get(root, root)
        inst = idx.get(sym.upper()) or idx.get(root)
        if not inst:
            continue
        core.append(ScanInstrument(
            inst.exchange, inst.tradingsymbol, inst.instrument_token, inst.segment,
            inst.name, "INDEX", True, root, inst.lot_size,
        ))
        used.add(inst.instrument_token)

    # 2. cash equities that have listed options (the liquid F&O single stocks)
    for root in sorted(nfo_roots - _INDEX_ROOTS):
        inst = cash.get(root)
        if not inst or inst.instrument_token in used:
            continue
        core.append(ScanInstrument(
            inst.exchange, inst.tradingsymbol, inst.instrument_token, inst.segment,
            inst.name, "EQUITY", True, root, inst.lot_size,
        ))
        used.add(inst.instrument_token)

    # 3. near-month commodity futures
    for root in sorted(mcx_roots):
        inst = commod.get(root)
        if not inst or inst.instrument_token in used:
            continue
        core.append(ScanInstrument(
            inst.exchange, inst.tradingsymbol, inst.instrument_token, inst.segment,
            inst.name, "COMMODITY", True, root, inst.lot_size,
        ))
        used.add(inst.instrument_token)

    core = core[:core_max]
    used = {c.instrument_token for c in core}

    # broad tier: the rest of the active NSE equity list, quote-screened only
    broad: list[ScanInstrument] = []
    for sym, inst in sorted(cash.items()):
        if inst.instrument_token in used:
            continue
        broad.append(ScanInstrument(
            inst.exchange, inst.tradingsymbol, inst.instrument_token, inst.segment,
            inst.name, "EQUITY", sym in nfo_roots, sym if sym in nfo_roots else None,
            inst.lot_size,
        ))
    broad = broad[:broad_max]

    return Universe(core=core, broad=broad, generated_at_day=date.today().isoformat())
