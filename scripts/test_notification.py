#!/usr/bin/env python3
"""Script to verify Telegram bot connectivity and test notification formatting."""

from datetime import datetime, timezone
from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from config.settings import load_settings
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


def main():
    settings = load_settings(BASE_DIR)
    db = Database(str(BASE_DIR / settings.database_path))
    notifier = TelegramNotifier(settings, db)

    if not notifier.is_configured():
        print("❌ Telegram is not configured in .env!")
        print("Please set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.")
        sys.exit(1)

    print("📡 Sending test notification to Telegram...")

    dummy_opp = NormalizedOpportunity(
        id="test_ping_001",
        source="radar_test",
        source_id="ping_1",
        title="[TEST] Python API & Scraping Script",
        description="This is a test notification confirming your Opportunity Radar bot is functioning.",
        url="https://github.com",
        created_at=datetime.now(timezone.utc),
        budget_min=50.0,
        budget_max=80.0,
        effective_budget=65.0,
        content_hash="test_ping_hash",
    )
    dummy_analysis = LLMAnalysis(
        task_type="test_verification",
        technical_fit=95.0,
        scope_fit=90.0,
        async_fit=100.0,
        experience_fit=90.0,
        clarity_fit=95.0,
        risk_level="low",
        estimated_hours=2.0,
        recommended_price=65.0,
        why=[
            "Telegram bot connectivity verified",
            "HTML formatting operational",
            "Radar online on VPS",
        ],
        red_flags=[],
    )
    dummy_score = ScoringResult(
        match_score=94.0,
        tier=OpportunityTier.HOT,
        technical_fit=95.0,
        scope_fit=90.0,
        budget_fit=90.0,
        async_fit=100.0,
        experience_fit=90.0,
        freshness_score=100.0,
        competition_score=100.0,
        estimated_hours=2.0,
        recommended_price=65.0,
    )
    processed = ProcessedOpportunity(
        opportunity=dummy_opp,
        filter_result=HardFilterResult(passed=True),
        analysis=dummy_analysis,
        score=dummy_score,
    )

    success = notifier.send_notification(processed)
    if success:
        print("✅ Test notification sent successfully to Telegram!")
    else:
        print("❌ Failed to deliver test notification. Check your token/chat_id.")


if __name__ == "__main__":
    main()
