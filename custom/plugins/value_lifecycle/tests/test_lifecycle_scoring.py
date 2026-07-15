from datetime import datetime, timedelta, timezone

import pytest

from lifecycle_scoring import (
    LifecyclePolicy,
    activity_score,
    lifecycle_decision,
    memory_strength_days,
    retrieval_score,
)


NOW = datetime(2026, 7, 15, tzinfo=timezone.utc)


def test_activity_follows_exponential_forgetting_curve():
    policy = LifecyclePolicy(base_decay_days=30.0)
    anchor = NOW - timedelta(days=30)

    score = activity_score(anchor, now=NOW, strength_days=30.0)

    assert score == pytest.approx(0.367879, rel=1e-5)


def test_effective_use_slows_forgetting_without_changing_value():
    value = 0.80
    weak = memory_strength_days(value, effective_use_count=0, base_days=30.0)
    strong = memory_strength_days(value, effective_use_count=5, base_days=30.0)

    assert strong > weak
    assert value == 0.80


def test_retrieval_score_prefers_relevant_valuable_active_memory():
    good = retrieval_score(
        similarity=0.90,
        value_score=0.85,
        activity_score_value=0.80,
        confidence=0.90,
        strength_score=0.70,
        token_cost=80,
    )
    stale = retrieval_score(
        similarity=0.90,
        value_score=0.40,
        activity_score_value=0.10,
        confidence=0.70,
        strength_score=0.30,
        token_cost=80,
    )

    assert good > stale


def test_protected_memory_never_auto_forgets():
    policy = LifecyclePolicy(dormant_threshold=0.25, forget_threshold=0.08)

    decision = lifecycle_decision(
        value_score=0.20,
        activity_score_value=0.01,
        protected=True,
        dormant_since=NOW - timedelta(days=365),
        now=NOW,
        policy=policy,
    )

    assert decision == "active"


def test_low_value_memory_dormants_before_grace_then_forgets():
    policy = LifecyclePolicy(
        dormant_threshold=0.25,
        forget_threshold=0.08,
        forget_value_threshold=0.55,
        forget_grace_days=14,
    )

    assert lifecycle_decision(
        value_score=0.40,
        activity_score_value=0.05,
        protected=False,
        dormant_since=None,
        now=NOW,
        policy=policy,
    ) == "dormant"

    assert lifecycle_decision(
        value_score=0.40,
        activity_score_value=0.05,
        protected=False,
        dormant_since=NOW - timedelta(days=15),
        now=NOW,
        policy=policy,
    ) == "forgotten"


def test_high_value_memory_can_sleep_but_is_not_auto_deleted():
    policy = LifecyclePolicy(
        dormant_threshold=0.25,
        forget_threshold=0.08,
        forget_value_threshold=0.55,
        forget_grace_days=14,
    )

    decision = lifecycle_decision(
        value_score=0.90,
        activity_score_value=0.01,
        protected=False,
        dormant_since=NOW - timedelta(days=365),
        now=NOW,
        policy=policy,
    )

    assert decision == "dormant"
