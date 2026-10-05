"""Unit tests for multi-variable scoring engine."""

from datetime import datetime, timedelta, timezone
from config.settings import UserProfile
from pipeline.models import LLMAnalysis, OpportunityTier
from pipeline.normalize import normalize_raw_item
from pipeline.scoring import ScoringEngine


def test_scoring_hot_opportunity():
    profile = UserProfile()
    engine = ScoringEngine(profile)
    now = datetime.now(timezone.utc)

    # Fresh opportunity, great budget, high technical fit
    item = normalize_raw_item(
        source="reddit",
        source_id="hot1",
        title="[Hiring] Python script to fix REST API bugs",
        description="Budget $60 flat. Quick task.",
        url="https://reddit.com/r/forhire/hot1",
        created_at=now - timedelta(minutes=30),
        raw_data={"num_comments": 1},
    )

    analysis = LLMAnalysis(
        task_type="python_api_bugfix",
        technical_fit=95.0,
        scope_fit=90.0,
        async_fit=100.0,
        experience_fit=90.0,
        clarity_fit=90.0,
        risk_level="low",
        estimated_hours=2.0,
        recommended_price=60.0,
        why=["Python", "REST API", "Small scope", "Async"],
        red_flags=[],
    )

    score = engine.calculate_score(item, analysis, ref_time=now)
    assert score.tier == OpportunityTier.HOT
    assert score.match_score >= 80.0
    assert score.freshness_score == 100.0
    assert score.competition_score == 100.0


def test_scoring_decay_with_age():
    profile = UserProfile()
    engine = ScoringEngine(profile)
    now = datetime.now(timezone.utc)

    # 30 hours old opportunity
    item = normalize_raw_item(
        source="reddit",
        source_id="old1",
        title="[Hiring] Python data parsing",
        description="Budget $50. Quick task.",
        url="https://reddit.com/r/forhire/old1",
        created_at=now - timedelta(hours=30),
    )

    analysis = LLMAnalysis(
        technical_fit=80.0,
        scope_fit=80.0,
        async_fit=80.0,
        experience_fit=80.0,
    )

    score = engine.calculate_score(item, analysis, ref_time=now)
    # Freshness for 30h old is 20
    assert score.freshness_score == 20.0


def test_scoring_zero_on_sync_violation():
    profile = UserProfile()
    engine = ScoringEngine(profile)
    now = datetime.now(timezone.utc)

    item = normalize_raw_item(
        source="reddit",
        source_id="sync_bad",
        title="Python API work",
        description="Budget $100.",
        url="https://example.com",
        created_at=now,
    )

    # Extreme async violation (< 20)
    analysis = LLMAnalysis(
        technical_fit=95.0,
        scope_fit=95.0,
        async_fit=10.0,  # Demands calls
        experience_fit=90.0,
    )

    score = engine.calculate_score(item, analysis, ref_time=now)
    assert score.match_score == 0.0
    assert score.tier == OpportunityTier.IGNORE
