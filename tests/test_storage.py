"""Tests for storage and database layer."""

from datetime import datetime, timezone
import pytest
from pipeline.models import (
    HardFilterResult,
    LLMAnalysis,
    NormalizedOpportunity,
    OpportunityStatus,
    OpportunityTier,
    ScoringResult,
)
from storage.database import Database


@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_radar.db"
    return Database(str(db_file))


def test_save_and_retrieve_opportunity(temp_db):
    opp = NormalizedOpportunity(
        id="test:123",
        source="reddit",
        source_id="123",
        title="Need Python script for scraping",
        description="Scrape data to CSV",
        url="https://reddit.com/r/forhire/123",
        author="client_user",
        created_at=datetime.now(timezone.utc),
        budget_min=50.0,
        budget_max=100.0,
        currency="USD",
        effective_budget=75.0,
        content_hash="abc123hash",
    )

    temp_db.save_opportunity(opp)
    assert temp_db.opportunity_exists("reddit", "123") is True
    assert (
        temp_db.opportunity_exists("reddit", "999", url=opp.url) is True
    )
    assert (
        temp_db.opportunity_exists("other", "999", content_hash="abc123hash")
        is True
    )
    assert temp_db.opportunity_exists("other", "nonexistent") is False


def test_analysis_persistence_and_summary(temp_db):
    opp = NormalizedOpportunity(
        id="test:456",
        source="reddit",
        source_id="456",
        title="Fix FastAPI endpoint",
        description="Fix bug in auth route",
        url="https://reddit.com/r/forhire/456",
        created_at=datetime.now(timezone.utc),
        content_hash="def456hash",
    )
    temp_db.save_opportunity(opp)

    filter_res = HardFilterResult(passed=True)
    analysis = LLMAnalysis(
        task_type="fastapi_bugfix",
        technical_fit=90.0,
        scope_fit=95.0,
        async_fit=100.0,
        experience_fit=85.0,
        clarity_fit=90.0,
        risk_level="low",
        estimated_hours=2.0,
        recommended_price=60.0,
        why=["FastAPI", "Python", "Quick bugfix"],
        red_flags=[],
    )
    score = ScoringResult(
        match_score=92.0,
        tier=OpportunityTier.HOT,
        technical_fit=90.0,
        scope_fit=95.0,
        budget_fit=80.0,
        async_fit=100.0,
        experience_fit=85.0,
        freshness_score=100.0,
        competition_score=80.0,
        estimated_hours=2.0,
        recommended_price=60.0,
        effective_budget=60.0,
    )

    temp_db.save_analysis(opp.id, filter_res, analysis, score)
    stats = temp_db.get_summary_stats()

    assert stats["total_opportunities"] == 1
    assert stats["passed_filters"] == 1
    assert stats["tier_hot"] == 1


def test_notification_tracking(temp_db):
    opp_id = "test:notif_test"
    opp = NormalizedOpportunity(
        id=opp_id,
        source="reddit",
        source_id="notif_test",
        title="Test notif",
        description="Test desc",
        url="https://example.com",
        created_at=datetime.now(timezone.utc),
        content_hash="hash_notif",
    )
    temp_db.save_opportunity(opp)

    assert temp_db.was_notified(opp_id, "telegram") is False
    temp_db.record_notification(opp_id, "telegram", "SENT")
    assert temp_db.was_notified(opp_id, "telegram") is True
