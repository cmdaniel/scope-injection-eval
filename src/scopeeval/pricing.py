"""Token accounting and cost, measured from the API's own usage meters.

Prices are USD per million tokens, as published in November 2026. Check current
prices before relying on any figure. Cache writes use the 5-minute TTL rate
(1.25x the input price); cache reads have their own per-model price.
"""

from __future__ import annotations

from typing import Any

# model: (input, output, cache read)
PRICES: dict[str, tuple[float, float, float]] = {
    "claude-opus-5-5": (4.00, 20.00, 0.20),
    "claude-sonnet-5-5": (2.00, 10.00, 0.10),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
}
CACHE_WRITE_MULTIPLIER = 1.25

USAGE_FIELDS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")


def empty_usage() -> dict[str, int]:
    return {"requests": 0, **{f: 0 for f in USAGE_FIELDS}}


def add_usage(total: dict[str, int], usage: Any) -> None:
    """Add one response's ``usage`` object (or dict) to a running total."""
    total["requests"] += 1
    if usage is None:
        return
    for f in USAGE_FIELDS:
        value = usage.get(f) if isinstance(usage, dict) else getattr(usage, f, None)
        total[f] += int(value or 0)


def cost(usage: dict[str, int], model: str) -> float | None:
    """Dollar cost of a usage total, or None when the model has no price on file."""
    if model not in PRICES:
        return None
    p_in, p_out, p_read = PRICES[model]
    return (
        usage.get("input_tokens", 0) * p_in
        + usage.get("cache_creation_input_tokens", 0) * p_in * CACHE_WRITE_MULTIPLIER
        + usage.get("cache_read_input_tokens", 0) * p_read
        + usage.get("output_tokens", 0) * p_out
    ) / 1e6


def uncached_cost(usage: dict[str, int], model: str) -> float | None:
    """What the same tokens would have cost with no prompt caching."""
    if model not in PRICES:
        return None
    p_in, p_out, _ = PRICES[model]
    all_input = sum(usage.get(f, 0) for f in USAGE_FIELDS if f != "output_tokens")
    return (all_input * p_in + usage.get("output_tokens", 0) * p_out) / 1e6


def usage_summary(usage: dict[str, int], model: str, seconds: float | None = None) -> dict[str, Any]:
    """Token meters plus their cost, ready to write next to a run's output."""
    summary: dict[str, Any] = {"model": model, **usage}
    total_input = sum(usage.get(f, 0) for f in USAGE_FIELDS if f != "output_tokens")
    summary["cache_read_share"] = round(usage.get("cache_read_input_tokens", 0) / total_input, 4) if total_input else 0.0
    spent, without = cost(usage, model), uncached_cost(usage, model)
    summary["cost_usd"] = round(spent, 6) if spent is not None else None
    summary["cost_usd_without_cache"] = round(without, 6) if without is not None else None
    if seconds is not None:
        summary["seconds"] = round(seconds, 2)
    return summary
