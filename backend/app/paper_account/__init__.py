"""A standalone discretionary paper-trading account.

Virtual funds, manual buy/sell of equities and F&O, positions that mark to
the live price, delivered stock in holdings, an order book, a trade book
and a funds ledger - a demo Kite account.

Isolated package: own tables (``app/models/paper_account.py``), own API
router, own lifespan tick loop. It reuses the instrument master, the live
tick state / Kite quotes, and the Indian cost model; it never touches the
strategy / deployment / OMS / live-order machinery.
"""
