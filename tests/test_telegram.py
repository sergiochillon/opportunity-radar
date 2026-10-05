"""Unit tests for Telegram formatting and notification dispatch."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
import pytest

from config.settings import AppSettings
from notifications.telegram import TelegramNotifier
from pipeline.models import (
    HardFilterResult,
    LLMAnalysis,
    NormalizedOpportunity,
    OpportunityTier,
    ProcessedOpportunity,
    ScoringResult,
)
from storage.database import Database


@pytest.fixture
def temp_db(tmp_path):
    return Database(str(tmp_path / "telegram_test.db"))


@pytest.fixture
def sample_item():
    opp = NormalizedOpportunity(
        id="sample_tg_1",
        source="reddit",
        source_id="tg_1",
        title="Need <Python> script & API fixes",
        description="Clean code without bugs",
        url="https://reddit.com/r/forhire/1",
        created_at=datetime.now(timezone.utc),
        budget_min=40.0,
        budget_max=60.0,
        effective_budget=50.0,
        content_hash="somehash",
    )
    analysis = LLMAnalysis(
        task_type="python_api_debugging",
        technical_fit=90.0,
        scope_fit=95.0,
        async_fit=100.0,
        experience_fit=90.0,
        estimated_hours=2.5,
        recommended_price=50.0,
        why=["Python & REST", "Small scope", "<Async> chat"],
        red_flags=["Tight deadline"],
    )
    score = ScoringResult(
        match_score=92.0,
        tier=OpportunityTier.HOT,
        technical_fit=90.0,
        scope_fit=95.0,
        budget_fit=90.0,
        async_fit=100.0,
        experience_fit=90.0,
        freshness_score=100.0,
        competition_score=80.0,
        estimated_hours=2.5,
        recommended_price=50.0,
    )
    return ProcessedOpportunity(
        opportunity=opp,
        filter_result=HardFilterResult(passed=True),
        analysis=analysis,
        score=score,
    )


def test_telegram_format_html_escaping(temp_db, sample_item):
    settings = AppSettings(telegram_bot_token="token", telegram_chat_id="123")
    notifier = TelegramNotifier(settings, temp_db)

    msg = notifier.format_message(sample_item)
    # Check that HTML entities are properly escaped
    assert "&lt;Python&gt;" in msg
    assert "&amp; API fixes" in msg
    assert "🔥 HOT | MATCH: 92/100" in msg
    assert "$40-$60" in msg
    assert "https://reddit.com/r/forhire/1" in msg


def test_telegram_send_success_and_deduplication(temp_db, sample_item):
    settings = AppSettings(
        telegram_bot_token="fake_token", telegram_chat_id="12345"
    )
    notifier = TelegramNotifier(settings, temp_db)
    temp_db.save_opportunity(sample_item.opportunity)

    mock_resp = MagicMock()
    mock_resp.status_code = 200

    with patch("httpx.Client.post", return_value=mock_resp):
        # First send -> should succeed
        res = notifier.send_notification(sample_item)
        assert res is True
        assert temp_db.was_notified(sample_item.opportunity.id) is True

        # Second send -> should be skipped (deduplicated)
        res_second = notifier.send_notification(sample_item)
        assert res_second is False
