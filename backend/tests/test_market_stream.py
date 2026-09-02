"""MarketStreamHub: per-client subscription, refcounting, fan-out, overflow."""

from __future__ import annotations

import asyncio

import pytest

from app.live.market_stream import MarketStreamHub


@pytest.mark.asyncio
async def test_refcount_tracks_upstream_need():
    hub = MarketStreamHub()
    a = await hub.add_client()
    b = await hub.add_client()

    assert await hub.subscribe(a, [(1, "AAA"), (2, "BBB")]) == [1, 2]  # newly needed
    assert await hub.subscribe(b, [(2, "BBB")]) == []                  # 2 already upstream

    assert await hub.unsubscribe(a, [2]) == []   # b still wants 2
    assert await hub.unsubscribe(b, [2]) == [2]  # now free upstream
    assert await hub.unsubscribe(a, [1]) == [1]


@pytest.mark.asyncio
async def test_publish_only_reaches_subscribers():
    hub = MarketStreamHub()
    a = await hub.add_client()
    b = await hub.add_client()
    await hub.subscribe(a, [(738561, "RELIANCE")])
    await hub.subscribe(b, [(408065, "INFY")])

    hub.publish({"instrument_token": 738561, "last_price": 1312.4, "ohlc": {"open": 1300}})

    msg = a.queue.get_nowait()
    assert msg["type"] == "tick"
    assert msg["symbol"] == "RELIANCE"
    assert msg["ltp"] == 1312.4
    assert b.queue.empty()


@pytest.mark.asyncio
async def test_remove_client_frees_tokens():
    hub = MarketStreamHub()
    a = await hub.add_client()
    await hub.subscribe(a, [(1, "AAA"), (2, "BBB")])
    assert sorted(await hub.remove_client(a)) == [1, 2]
    assert hub.status()["clients"] == 0


@pytest.mark.asyncio
async def test_overflow_drops_oldest_not_newest():
    hub = MarketStreamHub()
    a = await hub.add_client()
    await hub.subscribe(a, [(1, "AAA")])
    # fill past the queue cap
    for i in range(300):
        hub.publish({"instrument_token": 1, "last_price": float(i)})
    assert a.dropped > 0
    # the most recent price must still be enqueued
    prices = []
    while not a.queue.empty():
        prices.append(a.queue.get_nowait()["ltp"])
    assert prices[-1] == 299.0


@pytest.mark.asyncio
async def test_writer_style_drain():
    hub = MarketStreamHub()
    a = await hub.add_client()
    await hub.subscribe(a, [(1, "AAA")])
    hub.publish({"instrument_token": 1, "last_price": 10.0})
    got = await asyncio.wait_for(a.queue.get(), timeout=1)
    assert got["ltp"] == 10.0
