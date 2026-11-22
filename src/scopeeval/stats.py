"""Small, dependency-free statistics used in reports.

The point is to report uncertainty, not just point estimates: Wilson intervals
for rates, a seeded bootstrap for mean severity, Cohen's kappa for rater
agreement and the Mann-Whitney AUC for detectors.
"""

from __future__ import annotations

import math
import random
from collections import Counter
from collections.abc import Sequence

Z95 = 1.959963984540054


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float, float]:
    """Proportion with a Wilson score interval: (p, low, high)."""
    if n == 0:
        return (float("nan"), float("nan"), float("nan"))
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (p, max(0.0, centre - half), min(1.0, centre + half))


def bootstrap_mean(values: Sequence[float], reps: int = 2000, seed: int = 0) -> tuple[float, float, float]:
    """Mean with a percentile bootstrap 95% interval."""
    if not values:
        return (float("nan"), float("nan"), float("nan"))
    rng = random.Random(seed)
    n = len(values)
    means = sorted(sum(rng.choice(values) for _ in range(n)) / n for _ in range(reps))
    return (sum(values) / n, means[int(0.025 * reps)], means[int(0.975 * reps) - 1])


def cohen_kappa(a: Sequence[str], b: Sequence[str]) -> float:
    """Cohen's kappa for two raters' categorical labels."""
    if len(a) != len(b) or not a:
        raise ValueError("label lists must be non-empty and the same length")
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    expected = sum(ca[c] * cb[c] for c in set(ca) | set(cb)) / (n * n)
    if expected == 1.0:
        return 1.0
    return (observed - expected) / (1 - expected)


def auc(positive: Sequence[float], negative: Sequence[float]) -> float:
    """ROC AUC as the Mann-Whitney probability that a positive outscores a negative."""
    if not positive or not negative:
        return float("nan")
    wins = 0.0
    for p in positive:
        for q in negative:
            wins += 1.0 if p > q else 0.5 if p == q else 0.0
    return wins / (len(positive) * len(negative))


def required_n(p: float, half_width: float, z: float = Z95) -> int:
    """Episodes per cell for a normal-approximation CI of the given half-width."""
    return math.ceil(z * z * p * (1 - p) / (half_width * half_width))


def fmt_rate(k: int, n: int) -> str:
    p, lo, hi = wilson(k, n)
    if n == 0:
        return "n/a"
    return f"{p:.0%} [{lo:.0%}, {hi:.0%}]"
