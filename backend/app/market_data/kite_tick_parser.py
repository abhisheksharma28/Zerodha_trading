"""Zero-dependency parser for Zerodha Kite ticker binary frames.

Kite streams quotes as big-endian binary over WebSocket (Kite Connect v3):

    [int16 packet_count]
    repeated:
        [int16 packet_length]
        [packet_length bytes]

Packet layouts, distinguished by length:

    8    LTP           token, last_price
    28   index quote   token, ltp, high, low, open, close, change
    32   index full    the 28 above + exchange_timestamp
    44   quote         token, ltp, last_qty, avg_price, volume, buy_qty,
                       sell_qty, open, high, low, close
    184  full          the 44 above + last_trade_time, oi, oi_day_high,
                       oi_day_low, exchange_timestamp, and 10 depth entries
                       (5 bid, 5 ask): qty(i32), price(i32), orders(i16), pad(i16)

Prices are integers scaled by a per-segment divisor derived from the low
byte of the instrument token (100 for most, 10^7 for CDS currency, 10^4 for
BCD). A frame shorter than 2 bytes is a heartbeat and yields no ticks.

This module does NOT touch the network — it is pure bytes -> dicts so it can
be unit-tested against captured frames.
"""

from __future__ import annotations

import struct
from typing import Any

_SEGMENT_CDS = 3
_SEGMENT_BCD = 6


def _divisor(instrument_token: int) -> float:
    segment = instrument_token & 0xFF
    if segment == _SEGMENT_CDS:
        return 10_000_000.0
    if segment == _SEGMENT_BCD:
        return 10_000.0
    return 100.0


def _i32(buf: bytes, off: int) -> int:
    return struct.unpack_from(">i", buf, off)[0]


def _u16(buf: bytes, off: int) -> int:
    return struct.unpack_from(">H", buf, off)[0]


def _parse_packet(buf: bytes) -> dict[str, Any] | None:
    n = len(buf)
    if n < 8:
        return None
    token = _i32(buf, 0)
    div = _divisor(token)
    tick: dict[str, Any] = {"instrument_token": token}

    if n == 8:  # LTP
        tick["mode"] = "ltp"
        tick["last_price"] = _i32(buf, 4) / div
        return tick

    if n in (28, 32):  # index quote / full
        tick["mode"] = "index_full" if n == 32 else "index_quote"
        tick["last_price"] = _i32(buf, 4) / div
        tick["ohlc"] = {
            "high": _i32(buf, 8) / div,
            "low": _i32(buf, 12) / div,
            "open": _i32(buf, 16) / div,
            "close": _i32(buf, 20) / div,
        }
        tick["change"] = _i32(buf, 24) / div
        if n == 32:
            tick["exchange_timestamp"] = _i32(buf, 28)
        return tick

    if n >= 44:  # quote / full
        tick["mode"] = "full" if n >= 184 else "quote"
        tick["last_price"] = _i32(buf, 4) / div
        tick["last_traded_quantity"] = _i32(buf, 8)
        tick["average_traded_price"] = _i32(buf, 12) / div
        tick["volume_traded"] = _i32(buf, 16)
        tick["total_buy_quantity"] = _i32(buf, 20)
        tick["total_sell_quantity"] = _i32(buf, 24)
        tick["ohlc"] = {
            "open": _i32(buf, 28) / div,
            "high": _i32(buf, 32) / div,
            "low": _i32(buf, 36) / div,
            "close": _i32(buf, 40) / div,
        }
        if n >= 184:
            tick["last_trade_time"] = _i32(buf, 44)
            tick["oi"] = _i32(buf, 48)
            tick["oi_day_high"] = _i32(buf, 52)
            tick["oi_day_low"] = _i32(buf, 56)
            tick["exchange_timestamp"] = _i32(buf, 60)
            bids: list[dict[str, int | float]] = []
            asks: list[dict[str, int | float]] = []
            off = 64
            for i in range(10):
                qty = _i32(buf, off)
                price = _i32(buf, off + 4) / div
                orders = _u16(buf, off + 8)
                (asks if i >= 5 else bids).append(
                    {"quantity": qty, "price": price, "orders": orders}
                )
                off += 12
            tick["depth"] = {"buy": bids, "sell": asks}
        return tick

    return None


def parse_binary_message(data: bytes) -> list[dict[str, Any]]:
    """Return the list of tick dicts in one Kite binary frame. Heartbeats
    (frames shorter than 2 bytes) and malformed trailing bytes yield []."""
    if data is None or len(data) < 2:
        return []
    count = _u16(data, 0)
    ticks: list[dict[str, Any]] = []
    off = 2
    for _ in range(count):
        if off + 2 > len(data):
            break
        plen = _u16(data, off)
        off += 2
        if off + plen > len(data):
            break
        parsed = _parse_packet(data[off : off + plen])
        if parsed is not None:
            ticks.append(parsed)
        off += plen
    return ticks
