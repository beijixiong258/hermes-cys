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


def test_similarity_dominates_high_value_but_unrelated_memory():
    relevant = retrieval_score(
        similarity=0.82,
        value_score=0.60,
        activity_score_value=0.60,
        confidence=0.70,
        strength_score=0.30,
        token_cost=80,
    )
    unrelated_but_valuable = retrieval_score(
        similarity=0.30,
        value_score=1.00,
        activity_score_value=1.00,
        confidence=1.00,
        strength_score=1.00,
        token_cost=20,
    )

    assert relevant > unrelated_but_valuable


def test_protected_memory_never_auto_forgets():
    policy = LifecyclePolicy(forget_threshold=0.08)

    decision = lifecycle_decision(
        value_score=0.20,
        activity_score_value=0.01,
        protected=True,
        now=NOW,
        policy=policy,
    )

    assert decision == "active"


def test_low_value_memory_is_forgotten_immediately_without_dormancy():
    policy = LifecyclePolicy(
        forget_threshold=0.08,
        forget_value_threshold=0.55,
    )

    assert lifecycle_decision(
        value_score=0.40,
        activity_score_value=0.05,
        protected=False,
        now=NOW,
        policy=policy,
    ) == "forgotten"


def test_memory_above_activity_threshold_remains_active():
    policy = LifecyclePolicy(
        forget_threshold=0.08,
        forget_value_threshold=0.55,
    )

    assert lifecycle_decision(
        value_score=0.40,
        activity_score_value=0.10,
        protected=False,
        now=NOW,
        policy=policy,
    ) == "active"


def test_high_value_memory_stays_active_even_when_activity_is_low():
    policy = LifecyclePolicy(
        forget_threshold=0.08,
        forget_value_threshold=0.55,
    )

    decision = lifecycle_decision(
        value_score=0.90,
        activity_score_value=0.01,
        protected=False,
        now=NOW,
        policy=policy,
    )

    assert decision == "active"
