"""Unit tests for Reddit collector and client mocking."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
import pytest

from collectors.reddit.client import RedditClient
from collectors.reddit.collector import RedditCollector
from config.settings import AppSettings


@pytest.fixture
def mock_reddit_posts():
    return [
        {
            "id": "abc001",
            "title": "[Hiring] Need Python script to scrape 50 product pages",
            "selftext": "Budget is $50. Clean script needed to output to CSV.",
            "permalink": "/r/forhire/comments/abc001/need_python_script/",
            "author": "client_dan",
            "created_utc": 1728115200,
            "link_flair_text": "Hiring",
            "num_comments": 2,
            "subreddit": "forhire",
            "ups": 5,
        },
        {
            "id": "abc002",
            "title": "[TASK] Quick Python FastAPI bugfix [PAID]",
            "selftext": "Paying $40 to fix JWT authentication header issue.",
            "permalink": "/r/slavelabour/comments/abc002/fastapi_bugfix/",
            "author": "client_sam",
            "created_utc": 1728115500,
            "link_flair_text": "TASK",
            "num_comments": 4,
            "subreddit": "slavelabour",
            "ups": 3,
        },
    ]


def test_reddit_collector_mapping(mock_reddit_posts):
    settings = AppSettings(
        reddit_client_id="cid",
        reddit_client_secret="csecret",
        reddit_username="usr",
        reddit_password="pwd",
    )

    mock_client = MagicMock(spec=RedditClient)
    mock_client.is_configured = True
    mock_client.get_new_listings.return_value = mock_reddit_posts

    collector = RedditCollector(settings, client=mock_client)
    opps = collector.fetch_opportunities()

    assert len(opps) == 2

    first = opps[0]
    assert first.source == "reddit"
    assert first.source_id == "abc001"
    assert "Python script" in first.title
    assert first.author == "client_dan"
    assert first.effective_budget == 50.0
    assert first.raw_data["link_flair_text"] == "Hiring"
    assert first.raw_data["num_comments"] == 2
    assert "https://reddit.com/r/forhire" in first.url


def test_reddit_collector_unconfigured():
    settings = AppSettings(
        environment="development",
        reddit_client_id=None,
    )
    collector = RedditCollector(settings)
    opps = collector.fetch_opportunities()
    assert opps == []
