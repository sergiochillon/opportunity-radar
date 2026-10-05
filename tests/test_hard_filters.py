"""Unit tests for deterministic hard filters."""

from datetime import datetime, timezone
import pytest
from config.settings import UserProfile
from pipeline.hard_filters import HardFilterEngine
from pipeline.normalize import normalize_raw_item


@pytest.fixture
def filter_engine():
    profile = UserProfile(
        constraints={
            "remote_only": True,
            "async_only": True,
            "no_calls": True,
            "no_unpaid": True,
        }
    )
    return HardFilterEngine(profile)


def test_valid_python_bug_passes(filter_engine):
    item = normalize_raw_item(
        source="reddit",
        source_id="item1",
        title="[Hiring] Need Python developer to fix small API script",
        description="Budget $40. Send code and error logs asynchronously via chat.",
        url="https://reddit.com/r/forhire/item1",
        created_at=datetime.now(timezone.utc),
        raw_data={"link_flair_text": "Hiring"},
    )
    res = filter_engine.evaluate(item)
    assert res.passed is True
    assert len(res.rejection_reasons) == 0


def test_vendor_offer_for_hire_rejected(filter_engine):
    item = normalize_raw_item(
        source="reddit",
        source_id="item2",
        title="[For Hire] Full stack developer looking for work",
        description="I can build your website or script. DM me.",
        url="https://reddit.com/r/forhire/item2",
        created_at=datetime.now(timezone.utc),
        raw_data={"link_flair_text": "For Hire"},
    )
    res = filter_engine.evaluate(item)
    assert res.passed is False
    assert any("vendor_supply" in r for r in res.rejection_reasons)


def test_vendor_offer_slavelabour_flair_rejected(filter_engine):
    item = normalize_raw_item(
        source="reddit",
        source_id="item2b",
        title="I can scrape any website for you",
        description="Rates start at $10. Message me.",
        url="https://reddit.com/r/slavelabour/item2b",
        created_at=datetime.now(timezone.utc),
        raw_data={"link_flair_text": "OFFER"},
    )
    res = filter_engine.evaluate(item)
    assert res.passed is False
    assert any("vendor_supply" in r for r in res.rejection_reasons)


def test_purely_frontend_rejected(filter_engine):
    item = normalize_raw_item(
        source="reddit",
        source_id="item3",
        title="[Hiring] React / Next.js frontend redesign",
        description="Need expert in Tailwind CSS and Figma to build responsive UI landing page.",
        url="https://reddit.com/r/forhire/item3",
        created_at=datetime.now(timezone.utc),
        raw_data={"link_flair_text": "Hiring"},
    )
    res = filter_engine.evaluate(item)
    assert res.passed is False
    assert any("purely_frontend" in r for r in res.rejection_reasons)


def test_senior_years_rejected(filter_engine):
    item = normalize_raw_item(
        source="reddit",
        source_id="item4",
        title="[Hiring] Senior Django Engineer",
        description="Looking for candidate with 8+ years of experience in Django and distributed systems.",
        url="https://reddit.com/r/forhire/item4",
        created_at=datetime.now(timezone.utc),
        raw_data={"link_flair_text": "Hiring"},
    )
    res = filter_engine.evaluate(item)
    assert res.passed is False
    assert any("seniority_excessive" in r for r in res.rejection_reasons)


def test_unpaid_work_rejected(filter_engine):
    item = normalize_raw_item(
        source="reddit",
        source_id="item5",
        title="[Hiring] Unpaid internship for Python developers",
        description="Great learning opportunity for college students, work for equity.",
        url="https://reddit.com/r/forhire/item5",
        created_at=datetime.now(timezone.utc),
        raw_data={"link_flair_text": "Hiring"},
    )
    res = filter_engine.evaluate(item)
    assert res.passed is False
    assert any("unpaid" in r for r in res.rejection_reasons)


def test_mandatory_daily_meetings_rejected(filter_engine):
    item = normalize_raw_item(
        source="reddit",
        source_id="item6",
        title="[Hiring] Python API backend task",
        description="Budget $100. Must join daily standup zoom calls at 9am EST.",
        url="https://reddit.com/r/forhire/item6",
        created_at=datetime.now(timezone.utc),
        raw_data={"link_flair_text": "Hiring"},
    )
    res = filter_engine.evaluate(item)
    assert res.passed is False
    assert any("mandatory_sync" in r for r in res.rejection_reasons)


def test_safe_negation_passes_filter(filter_engine):
    # Tests negative lookbehind: "no calls", "without daily zoom"
    item = normalize_raw_item(
        source="reddit",
        source_id="item7",
        title="[Hiring] Python data parsing task",
        description="Need a script to clean CSVs. Budget $50. No calls required, 100% async communication.",
        url="https://reddit.com/r/forhire/item7",
        created_at=datetime.now(timezone.utc),
        raw_data={"link_flair_text": "Hiring"},
    )
    res = filter_engine.evaluate(item)
    assert res.passed is True
    assert len(res.rejection_reasons) == 0


def test_obvious_scam_rejected(filter_engine):
    item = normalize_raw_item(
        source="reddit",
        source_id="item8",
        title="[Hiring] Easy cashapp flip $500 today",
        description="Fast money just deposit $50 first and get instant transfer.",
        url="https://reddit.com/r/forhire/item8",
        created_at=datetime.now(timezone.utc),
        raw_data={"link_flair_text": "Hiring"},
    )
    res = filter_engine.evaluate(item)
    assert res.passed is False
    assert any("scam_or_spam" in r for r in res.rejection_reasons)
