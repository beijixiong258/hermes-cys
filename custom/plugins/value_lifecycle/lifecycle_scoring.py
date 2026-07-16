"""Pure scoring primitives for value-lifecycle memory.

The functions in this module are deliberately free of SQLite and wall-clock
side effects so lifecycle behaviour can be tested with a controlled clock.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


@dataclass(frozen=True)
class LifecyclePolicy:
    base_decay_days: float = 30.0
    forget_threshold: float = 0.08
    forget_value_threshold: float = 0.55


def clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def memory_strength_days(
    value_score: float,
    effective_use_count: int,
    *,
    base_days: float = 30.0,
    protected: bool = False,
) -> float:
    """Return the Ebbinghaus time constant for a memory.

    Intrinsic value changes the initial strength. Only effective use—not mere
    retrieval—extends the curve. Protected memories receive a longer display
    curve but are independently exempt from automatic forgetting.
    """
    value_factor = 0.50 + clamp(value_score)
    use_factor = 1.0 + 0.45 * math.log1p(max(0, int(effective_use_count)))
    protected_factor = 2.0 if protected else 1.0
    return max(1.0, float(base_days) * value_factor * use_factor * protected_factor)


def activity_score(
    anchor_at: datetime,
    *,
    now: Optional[datetime] = None,
    strength_days: float,
) -> float:
    """Compute activity using an exponential forgetting curve."""
    current = ensure_utc(now or datetime.now(timezone.utc))
    anchor = ensure_utc(anchor_at)
    elapsed_days = max(0.0, (current - anchor).total_seconds() / 86400.0)
    return clamp(math.exp(-elapsed_days / max(1.0, float(strength_days))))


def retrieval_score(
    *,
    similarity: float,
    value_score: float,
    activity_score_value: float,
    confidence: float,
    strength_score: float,
    token_cost: int,
) -> float:
    """Rank already-relevant memories; similarity remains dominant.

    Callers must apply their semantic hard gate before using this score.  This
    formula deliberately prevents a valuable but unrelated preference from
    outranking a directly relevant fact.
    """
    score = (
        0.60 * clamp(similarity)
        + 0.15 * clamp(confidence)
        + 0.10 * clamp(value_score)
        + 0.10 * clamp(activity_score_value)
        + 0.05 * clamp(strength_score)
    )
    cost_penalty = min(0.08, max(0, int(token_cost)) / 6000.0)
    return clamp(score - cost_penalty)


def lifecycle_decision(
    *,
    value_score: float,
    activity_score_value: float,
    protected: bool,
    now: Optional[datetime] = None,
    policy: Optional[LifecyclePolicy] = None,
) -> str:
    """Return ``active`` or ``forgotten``.

    There is no logical dormancy state: an unprotected memory is physically
    deleted as soon as both activity and value are below the configured
    forgetting thresholds. Protected and high-value memories stay active.
    """
    cfg = policy or LifecyclePolicy()
    if protected:
        return "active"
    if (
        clamp(activity_score_value) < cfg.forget_threshold
        and clamp(value_score) < cfg.forget_value_threshold
    ):
        return "forgotten"
    return "active"
