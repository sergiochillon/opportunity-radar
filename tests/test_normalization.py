"""Unit tests for normalization and budget parsing."""

from datetime import datetime, timezone
from pipeline.normalize import (
    compute_content_hash,
    normalize_content_text,
    normalize_raw_item,
    parse_budget_and_rates,
)


def test_parse_flat_budget():
    b_min, b_max, curr, is_hourly, eff = parse_budget_and_rates(
        "Need a Python script. Budget is $50. Clean code please."
    )
    assert b_min == 50.0
    assert b_max == 50.0
    assert curr == "USD"
    assert is_hourly is False
    assert eff == 50.0


def test_parse_range_budget():
    b_min, b_max, curr, is_hourly, eff = parse_budget_and_rates(
        "Small web scraping task, paying $30-$50 for 200 rows"
    )
    assert b_min == 30.0
    assert b_max == 50.0
    assert curr == "USD"
    assert is_hourly is False
    assert eff == 40.0


def test_parse_hourly_rate():
    b_min, b_max, curr, is_hourly, eff = parse_budget_and_rates(
        "Looking for Python developer to fix API bug at $25/hr"
    )
    assert b_min == 25.0
    assert is_hourly is True
    # Default 4 hours multiplier -> 25 * 4 = 100
    assert eff == 100.0


def test_parse_euro_currency():
    b_min, b_max, curr, is_hourly, eff = parse_budget_and_rates(
        "Script de automatización en Python, presupuesto 80€"
    )
    assert b_min == 80.0
    assert curr == "EUR"
    assert is_hourly is False
    assert eff == 80.0


def test_parse_no_budget():
    b_min, b_max, curr, is_hourly, eff = parse_budget_and_rates(
        "Need someone to help with Python script. Send your rates."
    )
    assert b_min is None
    assert b_max is None
    assert eff is None


def test_normalize_content_hash_resilience():
    # Two posts with different URLs and formatting should produce identical hashes
    text_a_title = "[Hiring] Need Python Developer to Scrape Products"
    text_a_desc = "Looking for someone to extract data to CSV. Details at https://mywebsite.com/info /u/poster1"

    text_b_title = "[TASK] Need Python developer to scrape products [PAID]"
    text_b_desc = "Looking for someone to extract data to CSV. Details at http://otherlink.org /u/otheruser"

    hash_a = compute_content_hash(text_a_title, text_a_desc)
    hash_b = compute_content_hash(text_b_title, text_b_desc)

    assert hash_a == hash_b


def test_normalize_raw_item_utc():
    item = normalize_raw_item(
        source="Reddit",
        source_id="abc1234",
        title="  Fix FastAPI auth route  ",
        description="Budget is $40 flat. Quick task.",
        url="https://reddit.com/r/forhire/abc1234",
        created_at=datetime(2026, 10, 5, 8, 0, 0),
        author="employer1",
    )
    assert item.source == "reddit"
    assert item.source_id == "abc1234"
    assert item.title == "Fix FastAPI auth route"
    assert item.created_at.tzinfo == timezone.utc
    assert item.effective_budget == 40.0
