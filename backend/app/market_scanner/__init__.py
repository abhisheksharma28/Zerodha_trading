"""Market Scanner - a 5-minute sweep of the tradable universe that turns
raw price/volume/fundamental data into ranked, trackable trade setups.

Isolated package. Reuses the instrument master, ``market_data_service``
candles, ``app.strategies.indicators`` and the Kite ticker; it does not
change strategies, backtesting, deployments or live execution.

Pipeline:  universe -> per-instrument (indicators + structure + fundamentals)
-> signals.evaluate -> rank -> options_overlay -> persist LIVE
-> tracker marks against real-time price -> EXPIRED with an outcome.

Everything is screener output with a transparent factor breakdown - never
advice, never a claim of profitability.
"""
