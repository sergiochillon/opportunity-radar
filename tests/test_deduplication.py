"""Unit tests for deduplication layer."""

from datetime import datetime, timezone
import pytest
from pipeline.deduplicate import Deduplicator
from pipeline.normalize import normalize_raw_item
from storage.database import Database


@pytest.fixture
def db(tmp_path):
    return Database(str(tmp_path / "dedup_test.db"))


def test_deduplicate_exact_source_id(db):
    dedup = Deduplicator(db)
    item1 = normalize_raw_item(
        source="reddit",
        source_id="post1",
        title="Python data cleaning",
        description="Clean 5 CSV files",
        url="https://reddit.com/r/forhire/post1",
        created_at=datetime.now(timezone.utc),
    )
    is_dup, _ = dedup.is_duplicate(item1)
    assert is_dup is False

    # Save to db
    db.save_opportunity(item1)

    # Check again
    is_dup, reason = dedup.is_duplicate(item1)
    assert is_dup is True
    assert "duplicate_source_id" in reason


def test_deduplicate_by_content_hash(db):
    dedup = Deduplicator(db)
    item_forhire = normalize_raw_item(
        source="reddit",
        source_id="post_forhire",
        title="[Hiring] Python script to merge excel spreadsheets",
        description="I have 10 excel files to merge into SQLite. Budget $50.",
        url="https://reddit.com/r/forhire/post_forhire",
        created_at=datetime.now(timezone.utc),
    )
    db.save_opportunity(item_forhire)

    # Same content reposted to r/slavelabour with different ID and URL
    item_slavelabour = normalize_raw_item(
        source="reddit",
        source_id="post_slavelabour",
        title="[TASK] Python script to merge excel spreadsheets [PAID]",
        description="I have 10 excel files to merge into SQLite. Budget $50.",
        url="https://reddit.com/r/slavelabour/post_slavelabour",
        created_at=datetime.now(timezone.utc),
    )

    is_dup, reason = dedup.is_duplicate(item_slavelabour)
    assert is_dup is True
    assert "duplicate_content_hash" in reason
