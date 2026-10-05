"""Unit tests for intelligence layer, schemas, and fallback estimator."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
import pytest

from config.settings import AppSettings, UserProfile
from intelligence.fallback import FallbackEstimator
from intelligence.llm_client import OpportunityAnalyzer
from intelligence.schemas import GeminiAnalysisOutput
from pipeline.normalize import normalize_raw_item


@pytest.fixture
def profile():
    return UserProfile(
        skills=["Python", "FastAPI", "SQL", "web scraping", "automation"],
        preferred_tasks=["bug fixing", "small scripts", "API integrations"],
    )


def test_schema_validation():
    data = {
        "task_type": "python_scraping",
        "technical_fit": 90.0,
        "scope_fit": 85.0,
        "async_fit": 95.0,
        "experience_fit": 90.0,
        "clarity_fit": 80.0,
        "risk_level": "low",
        "estimated_hours": 3.0,
        "recommended_price": 50.0,
        "why": ["Python scraping", "Clear scope"],
        "red_flags": [],
    }
    obj = GeminiAnalysisOutput(**data)
    assert obj.task_type == "python_scraping"
    assert obj.estimated_hours == 3.0


def test_fallback_estimator_small_task(profile):
    estimator = FallbackEstimator(profile)
    item = normalize_raw_item(
        source="reddit",
        source_id="small1",
        title="Need quick Python script to fix API bug",
        description="Fix endpoint returning 500 error in FastAPI. Budget $40.",
        url="https://example.com/1",
        created_at=datetime.now(timezone.utc),
    )

    analysis = estimator.estimate(item)
    assert analysis.is_fallback is True
    assert analysis.technical_fit >= 80.0
    assert analysis.scope_fit >= 80.0
    assert analysis.estimated_hours <= 4.0
    assert analysis.recommended_price == 40.0


def test_fallback_estimator_huge_saas(profile):
    estimator = FallbackEstimator(profile)
    item = normalize_raw_item(
        source="reddit",
        source_id="saas1",
        title="Build entire SaaS production platform from scratch",
        description="Complex architecture with dozens of services.",
        url="https://example.com/2",
        created_at=datetime.now(timezone.utc),
    )

    analysis = estimator.estimate(item)
    assert analysis.is_fallback is True
    assert analysis.scope_fit <= 50.0
    assert analysis.risk_level == "medium"


def test_analyzer_fallback_when_no_api_key(profile):
    settings = AppSettings(gemini_api_key=None)
    analyzer = OpportunityAnalyzer(settings, profile)

    item = normalize_raw_item(
        source="reddit",
        source_id="test_no_key",
        title="Python automation script needed",
        description="Clean 2 CSV files into SQL table. $50.",
        url="https://example.com/3",
        created_at=datetime.now(timezone.utc),
    )

    analysis = analyzer.analyze(item)
    assert analysis.is_fallback is True
    assert analysis.technical_fit >= 70.0
