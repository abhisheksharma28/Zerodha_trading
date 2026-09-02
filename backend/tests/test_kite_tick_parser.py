"""Kite ticker binary-frame parsing — against hand-built frames matching the
Kite Connect v3 spec."""

from __future__ import annotations

import struct

from app.market_data.kite_tick_parser import parse_binary_message

# tokens whose low byte is 1 -> equity divisor 100
INFY = 25601
# low byte 3 -> CDS currency divisor 10_000_000
USDINR = 259


def _frame(*packets: bytes) -> bytes:
    out = struct.pack(">H", len(packets))
    for p in packets:
        out += struct.pack(">H", len(p)) + p
    return out


def _ltp(token: int, price_paise: int) -> bytes:
    return struct.pack(">ii", token, price_paise)


def _quote(token: int, ltp: int, **k: int) -> bytes:
    return struct.pack(
        ">11i",
        token,
        ltp,
        k.get("last_qty", 0),
        k.get("avg", 0),
        k.get("volume", 0),
        k.get("buy_qty", 0),
        k.get("sell_qty", 0),
        k.get("open", 0),
        k.get("high", 0),
        k.get("low", 0),
        k.get("close", 0),
    )


def test_heartbeat_frame_yields_nothing():
    assert parse_binary_message(b"") == []
    assert parse_binary_message(b"\x00") == []


def test_single_ltp_packet():
    ticks = parse_binary_message(_frame(_ltp(INFY, 115_650)))
    assert len(ticks) == 1
    t = ticks[0]
    assert t["instrument_token"] == INFY
    assert t["mode"] == "ltp"
    assert t["last_price"] == 1156.50


def test_currency_segment_uses_1e7_divisor():
    ticks = parse_binary_message(_frame(_ltp(USDINR, 883_450_000)))
    assert ticks[0]["last_price"] == 88.345


def test_multiple_packets_in_one_frame():
    ticks = parse_binary_message(
        _frame(_ltp(INFY, 100_000), _ltp(USDINR, 800_000_000))
    )
    assert [t["instrument_token"] for t in ticks] == [INFY, USDINR]
    assert ticks[0]["last_price"] == 1000.0
    assert ticks[1]["last_price"] == 80.0


def test_quote_packet_fields():
    pkt = _quote(
        INFY,
        115_650,
        volume=1_000_000,
        buy_qty=5000,
        sell_qty=6000,
        open=114_000,
        high=116_000,
        low=113_500,
        close=113_800,
    )
    t = parse_binary_message(_frame(pkt))[0]
    assert t["mode"] == "quote"
    assert t["last_price"] == 1156.50
    assert t["volume_traded"] == 1_000_000
    assert t["total_buy_quantity"] == 5000
    assert t["total_sell_quantity"] == 6000
    assert t["ohlc"] == {"open": 1140.0, "high": 1160.0, "low": 1135.0, "close": 1138.0}


def test_full_packet_has_depth_and_oi():
    base = _quote(INFY, 115_650)
    extra = struct.pack(">5i", 1_700_000_000, 12345, 20000, 8000, 1_700_000_050)
    depth = b""
    for i in range(10):
        # bid prices below LTP, ask prices above
        price = 115_600 - i * 10 if i < 5 else 115_700 + (i - 5) * 10
        depth += struct.pack(">iiHH", (i + 1) * 100, price, i + 1, 0)
    t = parse_binary_message(_frame(base + extra + depth))[0]
    assert t["mode"] == "full"
    assert t["oi"] == 12345
    assert len(t["depth"]["buy"]) == 5
    assert len(t["depth"]["sell"]) == 5
    assert t["depth"]["buy"][0]["price"] == 1156.0
    assert t["depth"]["sell"][0]["price"] == 1157.0


def test_truncated_frame_stops_cleanly():
    good = _frame(_ltp(INFY, 100_000))
    # claim 3 packets but only supply one
    lying = struct.pack(">H", 3) + good[2:]
    ticks = parse_binary_message(lying)
    assert len(ticks) == 1  # parsed what it could, no exception
