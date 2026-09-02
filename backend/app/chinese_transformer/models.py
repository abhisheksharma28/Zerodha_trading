"""Baseline cross-sectional rankers (numpy only).

The spec's Phase 2: establish whether the features carry alpha with simple,
well-understood models before reaching for a Transformer. Two are provided:

* ``RidgeRanker``            — closed-form L2 linear regression on the
                               cross-sectional target.
* ``GradientBoostedRanker``  — shallow regression trees boosted on
                               residuals (compact CART, no sklearn).

Both are trained to predict the cross-sectional target (rank / bucket /
risk-adjusted) and their raw output is used only to *order* stocks, never
as a return forecast. ``CrossSectionalScaler`` is fit on training rows
only and reused unchanged at inference.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class CrossSectionalScaler:
    center: np.ndarray | None = None
    scale: np.ndarray | None = None

    def fit(self, x: np.ndarray) -> CrossSectionalScaler:
        self.center = np.nanmedian(x, axis=0)
        q1, q3 = np.nanpercentile(x, 25, axis=0), np.nanpercentile(x, 75, axis=0)
        iqr = q3 - q1
        self.scale = np.where(iqr < 1e-9, 1.0, iqr)
        return self

    def transform(self, x: np.ndarray) -> np.ndarray:
        if self.center is None or self.scale is None:
            raise RuntimeError("scaler not fit")
        z = (np.nan_to_num(x, nan=0.0) - self.center) / self.scale
        return np.clip(z, -8.0, 8.0)

    def fit_transform(self, x: np.ndarray) -> np.ndarray:
        return self.fit(x).transform(x)


@dataclass
class RidgeRanker:
    l2: float = 10.0
    _w: np.ndarray | None = None
    _b: float = 0.0
    feature_names: list[str] = field(default_factory=list)

    def fit(self, x: np.ndarray, y: np.ndarray) -> RidgeRanker:
        n, d = x.shape
        xb = np.hstack([x, np.ones((n, 1))])
        reg = self.l2 * np.eye(d + 1)
        reg[-1, -1] = 0.0
        beta = np.linalg.solve(xb.T @ xb + reg, xb.T @ y)
        self._w, self._b = beta[:-1], float(beta[-1])
        return self

    def predict(self, x: np.ndarray) -> np.ndarray:
        if self._w is None:
            raise RuntimeError("model not fit")
        return x @ self._w + self._b

    def feature_importance(self) -> dict[str, float]:
        if self._w is None:
            return {}
        imp = np.abs(self._w)
        s = imp.sum() or 1.0
        names = self.feature_names or [f"f{i}" for i in range(len(imp))]
        return dict(sorted(zip(names, (imp / s).tolist(), strict=False),
                           key=lambda kv: kv[1], reverse=True))


# --- compact regression tree -------------------------------------------

@dataclass
class _Node:
    feat: int = -1
    thr: float = 0.0
    left: _Node | None = None
    right: _Node | None = None
    value: float = 0.0


_SPLIT_BINS = 24  # candidate thresholds evaluated per feature (histogram split)


def _grow(x: np.ndarray, y: np.ndarray, depth: int, max_depth: int,
          min_leaf: int, rng: np.random.Generator, k_features: int) -> _Node:
    node = _Node(value=float(y.mean()))
    if depth >= max_depth or len(y) < 2 * min_leaf or np.ptp(y) < 1e-12:
        return node
    n, d = x.shape
    feats = rng.choice(d, size=min(k_features, d), replace=False)
    best_gain, best = 0.0, None
    # evaluate splits only at a fixed grid of order-statistic positions, so
    # the search is O(bins) per feature rather than O(n) — a histogram GBM.
    lo, hi = min_leaf, n - min_leaf
    if hi <= lo:
        return node
    cand_i = np.unique(np.linspace(lo, hi - 1, min(_SPLIT_BINS, hi - lo)).astype(int))
    for f in feats:
        col = x[:, f]
        order = np.argsort(col, kind="stable")
        cs, ys = col[order], y[order]
        csum = np.cumsum(ys)
        total = csum[-1]
        for i in cand_i:
            if cs[i] == cs[i - 1]:
                continue
            ln, rn = int(i), n - int(i)
            lsum, rsum = csum[i - 1], total - csum[i - 1]
            # reduction in SSE from this split (weighted sum-of-squares gain)
            gain = ((lsum * lsum) / ln + (rsum * rsum) / rn) - (total * total) / n
            if gain > best_gain:
                best_gain = gain
                best = (f, 0.5 * (cs[i] + cs[i - 1]))
    if best is None:
        return node
    f, thr = best
    mask = x[:, f] <= thr
    if mask.sum() < min_leaf or (~mask).sum() < min_leaf:
        return node
    node.feat, node.thr = int(f), float(thr)
    node.left = _grow(x[mask], y[mask], depth + 1, max_depth, min_leaf, rng, k_features)
    node.right = _grow(x[~mask], y[~mask], depth + 1, max_depth, min_leaf, rng, k_features)
    return node


def _predict_node(node: _Node, x: np.ndarray) -> np.ndarray:
    if node.feat < 0 or node.left is None or node.right is None:
        return np.full(len(x), node.value)
    out = np.empty(len(x))
    mask = x[:, node.feat] <= node.thr
    if mask.any():
        out[mask] = _predict_node(node.left, x[mask])
    if (~mask).any():
        out[~mask] = _predict_node(node.right, x[~mask])
    return out


def _count_uses(node: _Node, acc: dict[int, int]) -> None:
    if node.feat < 0 or node.left is None or node.right is None:
        return
    acc[node.feat] = acc.get(node.feat, 0) + 1
    _count_uses(node.left, acc)
    _count_uses(node.right, acc)


@dataclass
class GradientBoostedRanker:
    n_estimators: int = 80
    learning_rate: float = 0.06
    max_depth: int = 3
    min_leaf: int = 25
    subsample: float = 0.7
    feature_frac: float = 0.6
    seed: int = 0
    _trees: list[_Node] = field(default_factory=list)
    _base: float = 0.0
    feature_names: list[str] = field(default_factory=list)

    def fit(self, x: np.ndarray, y: np.ndarray) -> GradientBoostedRanker:
        rng = np.random.default_rng(self.seed)
        n, d = x.shape
        self._base = float(y.mean())
        pred = np.full(n, self._base)
        k = max(1, int(self.feature_frac * d))
        self._trees = []
        for _ in range(self.n_estimators):
            resid = y - pred
            if self.subsample < 1.0:
                idx = rng.choice(n, size=max(2 * self.min_leaf, int(self.subsample * n)),
                                 replace=False)
            else:
                idx = np.arange(n)
            tree = _grow(x[idx], resid[idx], 0, self.max_depth, self.min_leaf, rng, k)
            pred = pred + self.learning_rate * _predict_node(tree, x)
            self._trees.append(tree)
        return self

    def predict(self, x: np.ndarray) -> np.ndarray:
        if not self._trees:
            raise RuntimeError("model not fit")
        out = np.full(len(x), self._base)
        for t in self._trees:
            out += self.learning_rate * _predict_node(t, x)
        return out

    def feature_importance(self) -> dict[str, float]:
        acc: dict[int, int] = {}
        for t in self._trees:
            _count_uses(t, acc)
        total = sum(acc.values()) or 1
        names = self.feature_names or [f"f{i}" for i in range(len(acc))]
        imp = {names[i]: c / total for i, c in acc.items() if i < len(names)}
        return dict(sorted(imp.items(), key=lambda kv: kv[1], reverse=True))


RANKERS = {"ridge": RidgeRanker, "gbrt": GradientBoostedRanker}
