"""End-to-end integration tests for the Opportunity Radar pipeline."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from collectors.reddit.client import RedditClient
from collectors.reddit.collector import RedditCollector
from config.settings import AppSettings, UserProfile
from pipeline.models import OpportunityTier
from pipeline.orchestrator import RadarOrchestrator
from storage.database import Database

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "realistic_opportunities.json"


@pytest.fixture
def mock_reddit_collector(tmp_path):
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        fixtures = json.load(f)

    settings = AppSettings(
        reddit_client_id="dummy_id",
        reddit_client_secret="dummy_secret",
        reddit_username="dummy_user",
        reddit_password="dummy_pass",
    )
    mock_client = MagicMock(spec=RedditClient)
    mock_client.is_configured = True
    mock_client.get_new_listings.return_value = fixtures

    collector = RedditCollector(settings, client=mock_client)
    return collector, fixtures


def test_full_pipeline_e2e(tmp_path, mock_reddit_collector):
    collector, fixtures = mock_reddit_collector
    db_file = tmp_path / "e2e_radar.db"
    db = Database(str(db_file))

    settings = AppSettings(
        database_path=str(db_file),
        gemini_api_key=None,  # Tests deterministic fallback
    )
    profile = UserProfile(
        skills=["Python", "FastAPI", "SQL", "web scraping", "automation", "CSV"],
        preferred_tasks=["bug fixing", "small scripts", "automation"],
    )

    orchestrator = RadarOrchestrator(
        settings=settings,
        profile=profile,
        db=db,
        collectors=[collector],
    )

    # Mock Telegram network call
    with patch("httpx.Client.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        # First run: process all 8 items
        metrics = orchestrator.run_cycle()

        assert metrics["collected"] == 8
        # Case 2 (React), Case 3 (Senior US), Case 4 (Unpaid), Case 5 (Zoom meetings) -> Rejected by hard filters (4 rejected)
        assert metrics["rejected_hard_filters"] >= 4
        # Case 1 (FastAPI bug $50), Case 6 (CSV merge $50), Case 7 (huge SaaS), Case 8 (PDF extract) -> Analyzed (4 analyzed)
        assert metrics["analyzed_llm"] >= 3

        stats = db.get_summary_stats()
        assert stats["total_opportunities"] == 8

        # Verify that hot/good candidates were created
        assert stats["tier_hot"] + stats["tier_good"] >= 2

        # Second run with exact same feed -> All 8 should be flagged as duplicates!
        metrics_second = orchestrator.run_cycle()
        assert metrics_second["collected"] == 8
        assert metrics_second["duplicates"] == 8
        assert metrics_second["analyzed_llm"] == 0
        assert metrics_second["notified"] == 0
