"""Chronological splitting and walk-forward folds.

No random splits — financial data is temporal. Every fold enforces a
purge/embargo gap of ``horizon`` trading days between the last training
rebalance and the first test rebalance, so a training label (which peeks
``horizon`` days ahead) can never overlap the test window.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd


@dataclass(frozen=True)
class Fold:
    index: int
    train_start: date
    train_end: date
    test_start: date
    test_end: date

    def as_dict(self) -> dict[str, str | int]:
        return {
            "index": self.index,
            "train_start": self.train_start.isoformat(),
            "train_end": self.train_end.isoformat(),
            "test_start": self.test_start.isoformat(),
            "test_end": self.test_end.isoformat(),
        }


def _uniq_dates(index: pd.MultiIndex) -> list[pd.Timestamp]:
    return sorted({d for d, _s in index})


def walk_forward(
    panel_index: pd.MultiIndex,
    *,
    horizon: int,
    n_folds: int = 4,
    scheme: str = "expanding",       # "expanding" | "rolling"
    min_train: int = 120,           # minimum training rebalance dates
    test_size: int | None = None,
) -> list[Fold]:
    dates = _uniq_dates(panel_index)
    n = len(dates)
    if n < min_train + n_folds + horizon:
        # degrade to a single split rather than nothing
        n_folds = 1
    usable = n - min_train
    ts = test_size or max(1, usable // (n_folds + 1))
    folds: list[Fold] = []
    for k in range(n_folds):
        tr_end_i = min_train + k * ts
        te_start_i = tr_end_i + horizon
        te_end_i = min(te_start_i + ts, n) - 1
        if te_start_i >= n or te_end_i <= te_start_i:
            break
        tr_start_i = 0 if scheme == "expanding" else max(0, tr_end_i - min_train)
        folds.append(Fold(
            index=k,
            train_start=dates[tr_start_i].date(),
            train_end=dates[tr_end_i - 1].date(),
            test_start=dates[te_start_i].date(),
            test_end=dates[te_end_i].date(),
        ))
    return folds


def chronological_split(
    panel_index: pd.MultiIndex, *, horizon: int, train=0.6, val=0.2
) -> tuple[Fold, Fold]:
    """Single train / validation / test split (test is the remainder).
    Returned as two Folds: (train->val, train+val->test)."""
    dates = _uniq_dates(panel_index)
    n = len(dates)
    i_tr = int(n * train)
    i_val = int(n * (train + val))
    f1 = Fold(0, dates[0].date(), dates[max(0, i_tr - 1)].date(),
              dates[min(i_tr + horizon, n - 1)].date(), dates[max(0, i_val - 1)].date())
    f2 = Fold(1, dates[0].date(), dates[max(0, i_val - 1)].date(),
              dates[min(i_val + horizon, n - 1)].date(), dates[-1].date())
    return f1, f2
