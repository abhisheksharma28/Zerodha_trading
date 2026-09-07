"""Intraday Move Intelligence Engine (IMIE).

A 1-minute intraday scan that ranks NSE instruments by the empirical
probability of a significant move and places each in the
compression -> pressure -> breakout -> expansion state machine.

Isolated package: it reads the existing Kite client, the live tick feed
(`app/live`), order-flow capabilities (`app/orderflow`), the shared
indicators and the sector map; it writes only `imie_*` tables. See
`docs/IMIE.md`.
"""
