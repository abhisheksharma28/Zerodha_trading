"""Assemble the market-insights briefing from the platform's own services."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings
from app.core.logging import get_logger
from app.market_data.nse_universe import _KNOWN_SECTOR
from app.services.market_data_service import market_overview

logger = get_logger(__name__)


def _sign(v: float | None, digits: int = 2) -> str:
    if v is None:
        return "—"
    return f"{'+' if v >= 0 else ''}{v:.{digits}f}"


def _idx(ov: dict[str, Any], name: str) -> dict[str, Any] | None:
    for r in ov.get("indices", []):
        if r.get("symbol") == name:
            return r
    return None


def _vol_regime(vix: float | None) -> tuple[str, str]:
    if vix is None:
        return "unknown", "India VIX unavailable"
    if vix < 12:
        return "calm", "very low volatility — trend-following friendly, complacency risk"
    if vix < 15:
        return "low", "low volatility — orderly tape"
    if vix < 20:
        return "elevated", "rising volatility — tighten stops, expect chop"
    if vix < 28:
        return "high", "high volatility — reduce size, favour quality / defensives"
    return "extreme", "crisis-level volatility — capital preservation mode"


def _risk_tone(nifty_pct: float | None, ad_ratio: float | None, vix: float | None) -> tuple[str, str]:
    n = nifty_pct or 0.0
    ad = ad_ratio if ad_ratio is not None else 1.0
    if n >= 0.5 and ad >= 1.6 and (vix or 20) < 18:
        return "risk-on", "broad advance with healthy breadth"
    if n <= -0.5 and ad <= 0.7:
        return "risk-off", "broad decline, breadth is weak"
    if abs(n) < 0.3 and 0.8 <= ad <= 1.4:
        return "range-bound", "index flat, breadth balanced"
    if n > 0 and ad < 1.0:
        return "narrow / thin", "index up but more stocks falling than rising — a few heavyweights carrying it"
    if n < 0 and ad > 1.2:
        return "resilient", "index down but breadth positive — selling concentrated in the big names"
    return "mixed", "no clear directional signal"


def _scanner_digest(db: Session) -> dict[str, Any]:
    from app.market_scanner import service as scan_service

    try:
        data = scan_service.recommendations(db)
    except Exception as exc:  # noqa: BLE001
        logger.info("insights_scanner_failed", err=str(exc))
        return {"available": False}
    live = data.get("live") or []
    longs = [r for r in live if r.get("direction") == "LONG"]
    shorts = [r for r in live if r.get("direction") == "SHORT"]
    by_sector = Counter(_KNOWN_SECTOR.get(r.get("tradingsymbol", ""), "Other") for r in live)
    ranked = sorted(
        live,
        key=lambda r: ({"A": 0, "B": 1, "C": 2}.get(r.get("grade", "C"), 3), -(r.get("confidence") or 0)),
    )
    top = [
        {
            "symbol": r["tradingsymbol"], "direction": r["direction"],
            "style": r.get("trade_style"), "setup": r.get("setup_type"),
            "grade": r.get("grade"), "confidence": r.get("confidence"),
            "entry": r.get("entry"), "stop": r.get("stop_loss"), "target": r.get("target_1"),
            "rr": r.get("rr"),
        }
        for r in ranked[:6]
    ]
    return {
        "available": True,
        "live": len(live),
        "long": len(longs),
        "short": len(shorts),
        "long_pct": round(len(longs) / len(live) * 100.0, 0) if live else None,
        "top_sectors": by_sector.most_common(3),
        "top_ideas": top,
        "as_of": data.get("as_of"),
        "last_scan": (data.get("last_scan") or {}).get("at"),
    }


def _book_digest(db: Session, settings: Settings) -> dict[str, Any]:
    from app.baskets import service as basket_service
    from app.paper_account import service as paper_service

    try:
        summ = paper_service.summary(db, settings)
        holdings = paper_service.holdings(db, settings)
        positions = paper_service.positions(db, settings)
    except Exception as exc:  # noqa: BLE001
        logger.info("insights_book_failed", err=str(exc))
        return {"available": False}

    movers = sorted(
        (h for h in holdings if h.get("day_change_pct") is not None),
        key=lambda h: abs(h["day_change_pct"]), reverse=True,
    )[:4]
    alerts: list[str] = []
    if (summ.get("funds") or {}).get("available_margin", 0) < 0:
        alerts.append("Paper account has negative free cash — it is over-committed. Reconcile or Reset.")
    for h in holdings:
        if (h.get("day_change_pct") or 0) <= -5:
            alerts.append(f"{h['tradingsymbol']} is down {h['day_change_pct']}% today.")
    for p in positions:
        if (p.get("pnl_pct") or 0) <= -8:
            alerts.append(f"Position {p['tradingsymbol']} is at {p['pnl_pct']}%.")

    deployed: list[dict[str, Any]] = []
    try:
        for b in basket_service.list_baskets(db):
            if b.get("status") != "deployed":
                continue
            row = {"id": b["id"], "name": b["name"], "category": b.get("category")}
            try:
                from app.baskets import paper as basket_paper

                st = basket_paper.status(db, settings, b["id"])
                row.update(
                    value=st.get("portfolio_value"), return_pct=st.get("return_pct"),
                    rebalance_due=st.get("rebalance_due"),
                )
                if st.get("rebalance_due"):
                    alerts.append(f"Basket “{b['name']}” is due for a rebalance.")
            except Exception:  # noqa: BLE001
                pass
            deployed.append(row)
    except Exception as exc:  # noqa: BLE001
        logger.info("insights_baskets_failed", err=str(exc))

    pnl = summ.get("pnl") or {}
    return {
        "available": True,
        "net_worth": summ.get("net_worth"),
        "total_pnl": pnl.get("total"),
        "total_pnl_pct": pnl.get("total_pct"),
        "day_pnl": (pnl.get("positions_unrealized") or 0) + (pnl.get("holdings_day") or 0),
        "available_margin": (summ.get("funds") or {}).get("available_margin"),
        "counts": summ.get("counts"),
        "movers": [
            {"symbol": h["tradingsymbol"], "day_change_pct": h["day_change_pct"],
             "pnl_pct": h.get("pnl_pct")}
            for h in movers
        ],
        "deployed_baskets": deployed,
        "alerts": alerts[:6],
    }


def _seasonality_note() -> dict[str, Any] | None:
    try:
        from app.seasonality.store import load as load_seasonality
    except Exception:  # noqa: BLE001
        return None
    rep = load_seasonality()
    if not rep:
        return None
    cur = rep.get("current_month") or {}
    longs = [c["sector"].replace("NIFTY ", "") for c in (cur.get("long_candidates") or [])[:3]]
    shorts = [c["sector"].replace("NIFTY ", "") for c in (cur.get("short_candidates") or [])[:3]]
    return {
        "month": cur.get("name"),
        "anchor": cur.get("anchor"),
        "historical_long_tilt": longs,
        "historical_short_tilt": shorts,
        "verdict": rep.get("verdict"),
        "caveat": (
            "Descriptive calendar tilt only — the seasonality engine's verdict is "
            f"'{rep.get('verdict')}', so this is context, not a signal."
        ),
    }


def _narrative(pulse: dict[str, Any], sectors: dict[str, Any], scan: dict[str, Any],
               book: dict[str, Any]) -> tuple[str, list[str]]:
    n = pulse.get("nifty") or {}
    b = pulse.get("bank") or {}
    brd = pulse.get("breadth") or {}
    tone = pulse.get("risk_tone", "mixed")
    vixr = pulse.get("vol_regime", "unknown")

    lead = ", ".join(s["sector"] for s in sectors.get("leaders", [])[:2]) or "—"
    lag = ", ".join(s["sector"] for s in sectors.get("laggards", [])[:2]) or "—"

    parts = [
        f"Market read: **{tone}** ({pulse.get('risk_tone_why', '')}).",
        f"Nifty {_sign(n.get('change_pct'))}% at {n.get('ltp', '—')}, "
        f"Bank Nifty {_sign(b.get('change_pct'))}%.",
        f"Breadth {brd.get('advances', 0)} up / {brd.get('declines', 0)} down "
        f"(A/D {brd.get('ad_ratio', '—')}).",
        f"India VIX {pulse.get('vix', '—')} — {vixr} volatility.",
        f"{lead} leading; {lag} lagging.",
    ]
    if scan.get("available"):
        parts.append(
            f"The scanner has {scan.get('live', 0)} live ideas, "
            f"{scan.get('long_pct', 0):.0f}% long."
        )
    if book.get("available") and book.get("total_pnl_pct") is not None:
        parts.append(
            f"Your paper book is {_sign(book['total_pnl_pct'])}% overall "
            f"({_sign(book.get('day_pnl'), 0)} today)."
        )
    headline = " ".join(parts)

    bullets: list[str] = []
    tone_map = {
        "risk-on": "Trend-following and momentum have the wind at their back today.",
        "risk-off": "Defensive posture — the tape is broadly weak.",
        "narrow / thin": "Index strength is narrow. Be sceptical of the headline number.",
        "resilient": "Selling is concentrated in the heavyweights; the broader market is holding.",
        "range-bound": "No edge in direction — mean-reversion setups over breakouts.",
    }
    if tone in tone_map:
        bullets.append(tone_map[tone])
    if pulse.get("vix") is not None and pulse["vix"] >= 18:
        bullets.append(f"VIX at {pulse['vix']} — cut position size and widen stops.")
    if sectors.get("leaders"):
        top = sectors["leaders"][0]
        bullets.append(f"{top['sector']} is the strongest sector today ({_sign(top['avg_change_pct'])}%).")
    if scan.get("available") and scan.get("top_sectors"):
        s0 = scan["top_sectors"][0]
        if s0[1] >= 3:
            bullets.append(f"{s0[1]} of the scanner's live ideas are in {s0[0]} — a crowded theme.")
    if scan.get("available") and scan.get("long_pct") is not None:
        if scan["long_pct"] >= 75:
            bullets.append("Scanner ideas are heavily long-skewed — consistent with a risk-on tape.")
        elif scan["long_pct"] <= 30:
            bullets.append("Scanner ideas are short-skewed — it's finding more breakdowns than breakouts.")
    for a in book.get("alerts", [])[:3]:
        bullets.append("⚠ " + a)
    return headline, bullets


def build(db: Session, settings: Settings, *, universe: str = "nifty100") -> dict[str, Any]:
    ov = market_overview(db, settings, universe=universe)
    now = datetime.now(UTC).isoformat()
    if not ov.get("available"):
        return {"available": False, "reason": ov.get("reason", "market data unavailable"),
                "as_of": now}

    nifty = _idx(ov, "NIFTY 50") or {}
    bank = _idx(ov, "NIFTY BANK") or {}
    vix_row = _idx(ov, "INDIA VIX") or {}
    vix = vix_row.get("ltp")
    brd = ov.get("breadth") or {}
    vol_label, vol_why = _vol_regime(vix)
    tone, tone_why = _risk_tone(nifty.get("change_pct"), brd.get("ad_ratio"), vix)

    pulse = {
        "nifty": {"ltp": nifty.get("ltp"), "change_pct": nifty.get("change_pct")},
        "bank": {"ltp": bank.get("ltp"), "change_pct": bank.get("change_pct")},
        "vix": vix,
        "vol_regime": vol_label,
        "vol_regime_why": vol_why,
        "risk_tone": tone,
        "risk_tone_why": tone_why,
        "breadth": brd,
        "indices": ov.get("indices", []),
        "signals": ov.get("signals", {}),
    }
    sec_sorted = ov.get("sectors") or []
    sectors = {
        "leaders": sec_sorted[:3],
        "laggards": list(reversed(sec_sorted[-3:])),
        "all": sec_sorted,
    }
    movers = {
        "gainers": ov.get("gainers", [])[:6],
        "losers": ov.get("losers", [])[:6],
        "most_active": ov.get("most_active", [])[:6],
    }
    scan = _scanner_digest(db)
    book = _book_digest(db, settings)
    seasonality = _seasonality_note()

    headline, bullets = _narrative(pulse, sectors, scan, book)

    return {
        "available": True,
        "as_of": now,
        "universe": universe,
        "headline": headline,
        "bullets": bullets,
        "pulse": pulse,
        "sectors": sectors,
        "movers": movers,
        "scanner": scan,
        "book": book,
        "seasonality": seasonality,
    }
