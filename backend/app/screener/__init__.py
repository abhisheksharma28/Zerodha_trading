"""Stock Screener — a daily cross-sectional quant score for the liquid NSE
universe, bucketed BUY / HOLD / AVOID and surfaced in the Insights tab.

Isolated package. It reads the instrument master, the configured
fundamentals provider and Kite daily candles; it writes only its own two
tables (``screener_ratings`` / ``screener_runs``) and touches nothing in
strategies, backtesting or execution.
"""
