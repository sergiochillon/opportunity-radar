"""QA & Security edge cases automated tests for Opportunity Radar."""

from datetime import datetime, timezone
import os
import sqlite3
import threading
import time
from pathlib import Path
import pytest

from config.settings import AppSettings, load_settings, load_profile
from notifications.telegram import TelegramNotifier
from pipeline.models import (
    HardFilterResult,
    LLMAnalysis,
    NormalizedOpportunity,
    OpportunityStatus,
    OpportunityTier,
    ProcessedOpportunity,
    ScoringResult,
)
from pipeline.normalize import (
    normalize_raw_item,
    normalize_content_text,
    parse_budget_and_rates,
)
from pipeline.orchestrator import RadarOrchestrator
from collectors.base import BaseCollector
from storage.database import Database


# =========================================================================
# 1. SECURITY: Secret Redaction & Log Leaks
# =========================================================================

def test_app_settings_repr_redacts_secrets():
    """Verify sensitive credentials are never displayed in repr or str dumps."""
    settings = AppSettings(
        telegram_bot_token="mock_telegram_secret_token_12345",
        gemini_api_key="mock_gemini_api_key_secret_abcde",
        reddit_client_secret="mock_reddit_client_secret_xyz",
        reddit_password="mock_reddit_password_secret_123",
        github_pat="mock_github_pat_secret_abcde",
    )
    repr_str = repr(settings)
    assert "mock_telegram_secret_token_12345" not in repr_str
    assert "mock_gemini_api_key_secret_abcde" not in repr_str
    assert "mock_reddit_client_secret_xyz" not in repr_str
    assert "mock_reddit_password_secret_123" not in repr_str
    assert "mock_github_pat_secret_abcde" not in repr_str


def test_telegram_notifier_sanitizes_token_in_errors(tmp_path):
    """Verify that Telegram bot token is never saved in error_message or logged."""
    db_file = tmp_path / "notif_sec.db"
    db = Database(str(db_file))
    token = "mock_leakable_bot_secret_token_98765"
    settings = AppSettings(
        telegram_bot_token=token,
        telegram_chat_id="123456",
    )
    notifier = TelegramNotifier(settings, db)

    raw_err = f"Client error 404 for url https://api.telegram.org/bot{token}/sendMessage"
    sanitized = notifier._sanitize_token(raw_err)
    assert token not in sanitized
    assert "[REDACTED_BOT_TOKEN]" in sanitized


# =========================================================================
# 2. INPUT & PARSING: Telegram Injection, Null Bytes, Protocol Safety
# =========================================================================

def test_telegram_formatting_unsupported_protocols(tmp_path):
    """Verify non-HTTP/TG protocols like javascript: or file: are sanitized."""
    db = Database(str(tmp_path / "telegram_proto.db"))
    settings = AppSettings(telegram_bot_token="dummy", telegram_chat_id="123")
    notifier = TelegramNotifier(settings, db)

    opp = NormalizedOpportunity(
        id="proto_test",
        source="reddit",
        source_id="proto_1",
        title="Test Dangerous URL",
        description="Testing javascript and file protocols",
        url="javascript:alert('pwned')",
        created_at=datetime.now(timezone.utc),
        content_hash="proto_hash",
    )
    item = ProcessedOpportunity(
        opportunity=opp,
        filter_result=HardFilterResult(passed=True),
        score=ScoringResult(
            match_score=85.0,
            tier=OpportunityTier.HOT,
            technical_fit=90.0,
            scope_fit=90.0,
            budget_fit=80.0,
            async_fit=90.0,
            experience_fit=90.0,
            freshness_score=90.0,
            competition_score=80.0,
            estimated_hours=3.0,
            recommended_price=50.0,
        ),
    )
    msg = notifier.format_message(item)
    # Must NOT render javascript: within an <a href="..."> tag
    assert '<a href="javascript:alert(\'pwned\')">' not in msg
    assert '<a href="javascript:' not in msg


def test_telegram_formatting_null_byte_resilience(tmp_path):
    """Verify null bytes in strings are safely stripped and do not break formatting."""
    db = Database(str(tmp_path / "telegram_null.db"))
    settings = AppSettings(telegram_bot_token="dummy", telegram_chat_id="123")
    notifier = TelegramNotifier(settings, db)

    opp = NormalizedOpportunity(
        id="null_opp",
        source="red\x00dit",
        source_id="null_1",
        title="Python Script \x00 with Null Bytes",
        description="Description \x00 with Null Bytes",
        url="https://example.com/item\x00",
        created_at=datetime.now(timezone.utc),
        content_hash="null_hash",
    )
    analysis = LLMAnalysis(
        task_type="bug\x00fix",
        why=["Fits \x00 Python well"],
        red_flags=["Caution \x00 flag"],
    )
    item = ProcessedOpportunity(
        opportunity=opp,
        filter_result=HardFilterResult(passed=True),
        analysis=analysis,
        score=ScoringResult(
            match_score=80.0,
            tier=OpportunityTier.GOOD,
            technical_fit=80.0,
            scope_fit=80.0,
            budget_fit=80.0,
            async_fit=90.0,
            experience_fit=80.0,
            freshness_score=80.0,
            competition_score=80.0,
            estimated_hours=2.0,
            recommended_price=40.0,
        ),
    )
    msg = notifier.format_message(item)
    assert "\x00" not in msg
    assert "Python Script  with Null Bytes" in msg


def test_telegram_message_length_bounded(tmp_path):
    """Verify extremely long titles or bullets cannot overflow 4096-char Telegram limit."""
    db = Database(str(tmp_path / "telegram_length.db"))
    settings = AppSettings(telegram_bot_token="dummy", telegram_chat_id="123")
    notifier = TelegramNotifier(settings, db)

    huge_title = "Massive Python Task " * 200  # 4000+ chars
    opp = NormalizedOpportunity(
        id="huge_title_opp",
        source="reddit",
        source_id="huge_1",
        title=huge_title,
        description="Short description",
        url="https://example.com/huge",
        created_at=datetime.now(timezone.utc),
        content_hash="huge_hash",
    )
    item = ProcessedOpportunity(
        opportunity=opp,
        filter_result=HardFilterResult(passed=True),
    )
    msg = notifier.format_message(item)
    assert len(msg) < 4096
    assert len(msg) <= 1500  # Title was truncated cleanly to ~280 chars


# =========================================================================
# 3. EDGE CASES IN NORMALIZATION
# =========================================================================

def test_normalize_raw_item_with_none_and_nulls():
    """Verify normalize_raw_item handles None, missing dates, and null bytes cleanly."""
    opp = normalize_raw_item(
        source="reddit",
        source_id="null_edge_1",
        title=None,
        description=None,
        url=None,
        created_at=None,
        author=None,
    )
    assert opp.title == ""
    assert opp.description == ""
    assert opp.url == ""
    assert opp.author is None
    assert opp.created_at.tzinfo == timezone.utc
    assert opp.id is not None
    assert opp.content_hash is not None


def test_parse_budget_edge_cases():
    """Verify budget parser handles out-of-range, negative, and extreme inputs."""
    # Negative budget
    b_min, b_max, curr, hourly, eff = parse_budget_and_rates("Budget: -$500")
    assert eff is None

    # Zero budget
    b_min, b_max, curr, hourly, eff = parse_budget_and_rates("Budget is $0")
    assert eff is None

    # Absurdly high number (> $50,000)
    b_min, b_max, curr, hourly, eff = parse_budget_and_rates("Budget $999999999999")
    assert eff is None

    # Empty string
    b_min, b_max, curr, hourly, eff = parse_budget_and_rates("")
    assert eff is None


# =========================================================================
# 4. CONCURRENCY & SQLITE LOCKING
# =========================================================================

def test_sqlite_concurrent_transactions(tmp_path):
    """Verify multiple concurrent worker threads can commit without deadlock or lock errors."""
    db_file = tmp_path / "concurrent.db"
    db = Database(str(db_file))

    errors = []

    def worker(worker_id: int):
        try:
            for i in range(10):
                opp = NormalizedOpportunity(
                    id=f"opp_{worker_id}_{i}",
                    source="reddit",
                    source_id=f"{worker_id}_{i}",
                    title=f"Worker {worker_id} Job {i}",
                    description="Valid description",
                    url=f"https://reddit.com/{worker_id}/{i}",
                    created_at=datetime.now(timezone.utc),
                    content_hash=f"hash_{worker_id}_{i}",
                )
                db.save_opportunity(opp)
                time.sleep(0.005)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0
    stats = db.get_summary_stats()
    assert stats["total_opportunities"] == 50


def test_sqlite_transaction_rollback_when_locked(tmp_path):
    """Verify transaction context manager cleanly raises 'database is locked' without masking."""
    db_file = tmp_path / "lock_clean.db"
    db = Database(str(db_file))

    # Hold exclusive lock on connection 1 with tiny timeout
    conn1 = db.get_connection()
    conn1.execute("PRAGMA busy_timeout = 50;")
    conn1.execute("BEGIN IMMEDIATE;")
    conn1.execute("CREATE TABLE dummy_lock (val INT);")

    # Connection 2 attempts transaction with tiny timeout
    with pytest.raises(sqlite3.OperationalError) as exc_info:
        with db.transaction() as conn2:
            conn2.execute("PRAGMA busy_timeout = 50;")
            conn2.execute("INSERT INTO dummy_lock VALUES (1);")

    # Verify the error is strictly 'database is locked', NOT 'cannot rollback'
    assert "database is locked" in str(exc_info.value).lower()
    conn1.execute("ROLLBACK;")
    conn1.close()


# =========================================================================
# 5. PIPELINE FAULT ISOLATION
# =========================================================================

class FaultyCollector(BaseCollector):
    def __init__(self):
        super().__init__(name="faulty")

    def fetch_opportunities(self):
        valid_opp = NormalizedOpportunity(
            id="valid_1",
            source="faulty",
            source_id="v1",
            title="Python script to scrape tables",
            description="Simple python scraping task, budget $60",
            url="https://example.com/v1",
            created_at=datetime.now(timezone.utc),
            content_hash="valid_hash_1",
        )
        # Create an item that might trigger an unexpected error during scoring/saving
        malformed_opp = NormalizedOpportunity(
            id="faulty_2",
            source="faulty",
            source_id="f2",
            title="Broken item",
            description="Broken",
            url="https://example.com/f2",
            created_at=datetime.now(timezone.utc),
            content_hash="broken_hash",
        )
        return [valid_opp, malformed_opp]


def test_pipeline_fault_isolation(tmp_path, monkeypatch):
    """Verify that a single failing opportunity does not crash the entire cycle."""
    db = Database(str(tmp_path / "pipeline_isolation.db"))
    settings = AppSettings(database_path=str(tmp_path / "pipeline_isolation.db"))
    from config.settings import UserProfile
    profile = UserProfile()

    orchestrator = RadarOrchestrator(
        settings, profile, db=db, collectors=[FaultyCollector()]
    )

    # Monkeypatch hard_filters to raise an unexpected error ONLY on faulty_2
    original_eval = orchestrator.hard_filters.evaluate

    def mock_eval(opp):
        if opp.id == "faulty_2":
            raise RuntimeError("Simulated unhandled exception on malformed item")
        return original_eval(opp)

    monkeypatch.setattr(orchestrator.hard_filters, "evaluate", mock_eval)

    # Run cycle: should not raise RuntimeError; valid_1 should still be processed
    metrics = orchestrator.run_cycle()
    assert metrics["collected"] == 2
    assert metrics["analyzed_llm"] >= 1


# =========================================================================
# 6. CONFIG & PROFILE RESILIENCE
# =========================================================================

def test_load_settings_invalid_poll_interval(tmp_path, monkeypatch):
    """Verify that negative or non-integer poll intervals fallback to 15 safely."""
    monkeypatch.setenv("POLL_INTERVAL_MINUTES", "-10")
    s = load_settings(tmp_path)
    assert s.poll_interval_minutes == 15

    monkeypatch.setenv("POLL_INTERVAL_MINUTES", "not_a_number")
    s2 = load_settings(tmp_path)
    assert s2.poll_interval_minutes == 15


def test_load_profile_corrupted_yaml(tmp_path):
    """Verify that malformed or non-mapping profile YAML falls back safely without crash."""
    bad_yaml = tmp_path / "corrupt_profile.yaml"
    bad_yaml.write_text("- list_item_not_mapping\n- another_item\n", encoding="utf-8")

    profile = load_profile(bad_yaml)
    assert isinstance(profile.skills, list)
    assert profile.budget.minimum == 10.0
