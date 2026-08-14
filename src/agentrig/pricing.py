"""Apply a frozen pricing snapshot to normalized provider usage."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from .canonical import canonical_hash
from .profiles.schemas import PricingSnapshot

_MILLION = Decimal(1_000_000)


def apply_pricing_snapshot(
    usage: dict[str, Any],
    snapshot: PricingSnapshot | None,
) -> dict[str, Any]:
    """Return usage enriched with cost only when every required input is known.

    The returned cost carries the complete frozen-snapshot identity. Reports only
    aggregate this value; they never look up today's prices or silently treat a
    missing token field as zero.
    """

    if snapshot is None:
        return dict(usage)
    model = _string(usage.get("model"))
    if model is None:
        return dict(usage)
    rate = next((item for item in snapshot.rates if item.model == model), None)
    if rate is None:
        return dict(usage)
    input_tokens = _token_count(usage, "input_tokens", "inputTokens", "prompt_tokens")
    output_tokens = _token_count(
        usage,
        "output_tokens",
        "outputTokens",
        "completion_tokens",
    )
    if input_tokens is None or output_tokens is None:
        return dict(usage)

    cached_tokens = _token_count(
        usage,
        "cached_input_tokens",
        "cachedInputTokens",
    )
    if cached_tokens is None:
        details = usage.get("prompt_tokens_details")
        if isinstance(details, dict):
            cached_tokens = _token_count(details, "cached_tokens")
    if rate.cached_input_per_million is not None and cached_tokens is None:
        return dict(usage)
    resolved_cached = cached_tokens or 0
    if resolved_cached > input_tokens:
        return dict(usage)

    regular_input = input_tokens - resolved_cached
    amount = Decimal(regular_input) * rate.input_per_million
    if resolved_cached:
        cached_rate = rate.cached_input_per_million
        if cached_rate is None:
            # A provider without a separate cache tier bills cached input at the
            # ordinary input rate; no token is dropped from the estimate.
            cached_rate = rate.input_per_million
        amount += Decimal(resolved_cached) * cached_rate
    amount += Decimal(output_tokens) * rate.output_per_million
    amount /= _MILLION

    enriched = dict(usage)
    enriched["model"] = model
    enriched["cost"] = {
        "amount": _decimal_text(amount),
        "currency": snapshot.currency,
        "kind": "estimated",
        "pricing_source": snapshot.source,
        "pricing_effective_at": snapshot.effective_at.isoformat(),
        "pricing_snapshot_hash": canonical_hash(snapshot),
    }
    return enriched


def _token_count(value: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        candidate = value.get(key)
        if isinstance(candidate, bool):
            continue
        if isinstance(candidate, int) and candidate >= 0:
            return candidate
    return None


def _string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _decimal_text(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return text if text != "-0" else "0"
