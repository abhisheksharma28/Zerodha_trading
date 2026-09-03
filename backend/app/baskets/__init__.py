"""Baskets — smallcase-style portfolios of sleeves, held and rebalanced.

Public surface:
  - ``spec``      : parse / validate a basket definition
  - ``engine``    : resolve target weights + plan the rebalance diff
  - ``backtest``  : walk-forward backtest of a basket
  - ``templates`` : starter basket definitions
"""

from app.baskets.spec import BasketSpec, SleeveSpec, SpecError, parse_spec

__all__ = ["BasketSpec", "SleeveSpec", "SpecError", "parse_spec"]
