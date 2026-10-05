"""SQLite storage and repository for Opportunity Radar.

Configured with WAL mode, busy timeouts, and fast atomic transactions.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Dict, Generator, List, Optional

from pipeline.models import (
    HardFilterResult,
    LLMAnalysis,
    NormalizedOpportunity,
    OpportunityStatus,
    OpportunityTier,
    ScoringResult,
)


class Database:
    def __init__(self, db_path: str = "data/radar.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    def get_connection(self) -> sqlite3.Connection:
        """Create a new SQLite connection with WAL mode and busy timeout."""
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=10.0,
            check_same_thread=False,
            isolation_level=None,  # Autocommit mode by default
        )
        conn.row_factory = sqlite3.Row
        # Execute SQLite performance and concurrency pragmas
        conn.execute("PRAGMA busy_timeout = 10000;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager for short atomic transactions."""
        conn = self.get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE;")
            yield conn
            conn.execute("COMMIT;")
        except Exception:
            if conn.in_transaction:
                try:
                    conn.execute("ROLLBACK;")
                except Exception:
                    pass
            raise
        finally:
            conn.close()

    def init_schema(self) -> None:
        """Initialize database schema and indices idempotently."""
        conn = self.get_connection()
        try:
            # Set WAL journal mode once at schema initialization
            conn.execute("PRAGMA journal_mode = WAL;")
            with conn:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS opportunities (
                        id TEXT PRIMARY KEY,
                        source TEXT NOT NULL,
                        source_id TEXT NOT NULL,
                        title TEXT NOT NULL,
                        description TEXT,
                        url TEXT NOT NULL,
                        author TEXT,
                        created_at TEXT NOT NULL,
                        found_at TEXT NOT NULL,
                        budget_min REAL,
                        budget_max REAL,
                        currency TEXT DEFAULT 'USD',
                        is_hourly INTEGER DEFAULT 0,
                        effective_budget REAL,
                        location TEXT,
                        is_remote INTEGER DEFAULT 1,
                        content_hash TEXT NOT NULL,
                        raw_data_json TEXT,
                        status TEXT NOT NULL DEFAULT 'NEW'
                    );

                    CREATE TABLE IF NOT EXISTS analyses (
                        opportunity_id TEXT PRIMARY KEY REFERENCES opportunities(id) ON DELETE CASCADE,
                        passed_hard_filters INTEGER NOT NULL,
                        rejection_reasons_json TEXT,
                        match_score REAL,
                        tier TEXT,
                        task_type TEXT,
                        technical_fit REAL,
                        scope_fit REAL,
                        budget_fit REAL,
                        async_fit REAL,
                        experience_fit REAL,
                        freshness_score REAL,
                        competition_score REAL,
                        risk_level TEXT,
                        estimated_hours REAL,
                        recommended_price REAL,
                        why_json TEXT,
                        red_flags_json TEXT,
                        is_fallback INTEGER DEFAULT 0,
                        analyzed_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS notifications (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        opportunity_id TEXT NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
                        channel TEXT NOT NULL,
                        status TEXT NOT NULL,
                        sent_at TEXT NOT NULL,
                        error_message TEXT
                    );

                    CREATE TABLE IF NOT EXISTS feedback (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        opportunity_id TEXT NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
                        feedback_type TEXT NOT NULL,
                        notes TEXT,
                        created_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS applications (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        opportunity_id TEXT NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
                        applied_at TEXT NOT NULL,
                        proposal_notes TEXT,
                        status TEXT NOT NULL DEFAULT 'SUBMITTED'
                    );

                    -- Indices for fast deduplication and filtering
                    CREATE INDEX IF NOT EXISTS idx_opp_source_id ON opportunities(source, source_id);
                    CREATE INDEX IF NOT EXISTS idx_opp_url ON opportunities(url);
                    CREATE INDEX IF NOT EXISTS idx_opp_content_hash ON opportunities(content_hash);
                    CREATE INDEX IF NOT EXISTS idx_opp_author_created ON opportunities(author, created_at);
                    CREATE INDEX IF NOT EXISTS idx_opp_status ON opportunities(status);
                    CREATE INDEX IF NOT EXISTS idx_notif_opp ON notifications(opportunity_id);
                    CREATE INDEX IF NOT EXISTS idx_analysis_tier ON analyses(tier);
                    """
                )
        finally:
            conn.close()

    def opportunity_exists(
        self,
        source: str,
        source_id: str,
        url: Optional[str] = None,
        content_hash: Optional[str] = None,
    ) -> bool:
        """Check if an opportunity already exists by (source, source_id), URL or content hash."""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            # 1. Direct match on (source, source_id)
            cursor.execute(
                "SELECT 1 FROM opportunities WHERE source = ? AND source_id = ? LIMIT 1",
                (source, source_id),
            )
            if cursor.fetchone():
                return True

            # 2. Match on URL
            if url:
                cursor.execute(
                    "SELECT 1 FROM opportunities WHERE url = ? LIMIT 1",
                    (url,),
                )
                if cursor.fetchone():
                    return True

            # 3. Match on content hash
            if content_hash:
                cursor.execute(
                    "SELECT 1 FROM opportunities WHERE content_hash = ? LIMIT 1",
                    (content_hash,),
                )
                if cursor.fetchone():
                    return True

            return False
        finally:
            conn.close()

    def is_recent_crosspost(
        self, author: Optional[str], created_at: datetime, window_hours: float = 6.0
    ) -> bool:
        """Check if the same author published a similar opportunity within window_hours."""
        if not author:
            return False

        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT created_at FROM opportunities WHERE author = ? ORDER BY created_at DESC LIMIT 5",
                (author,),
            )
            rows = cursor.fetchall()
            for row in rows:
                try:
                    prev_time = datetime.fromisoformat(row["created_at"])
                    if prev_time.tzinfo is None:
                        prev_time = prev_time.replace(tzinfo=timezone.utc)
                    curr_time = created_at
                    if curr_time.tzinfo is None:
                        curr_time = curr_time.replace(tzinfo=timezone.utc)
                    diff_hours = abs((curr_time - prev_time).total_seconds()) / 3600.0
                    if diff_hours <= window_hours:
                        return True
                except Exception:
                    continue
            return False
        finally:
            conn.close()

    def save_opportunity(self, opp: NormalizedOpportunity) -> None:
        """Insert or replace an opportunity in the database."""
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO opportunities (
                    id, source, source_id, title, description, url, author,
                    created_at, found_at, budget_min, budget_max, currency,
                    is_hourly, effective_budget, location, is_remote,
                    content_hash, raw_data_json, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    opp.id,
                    opp.source,
                    opp.source_id,
                    opp.title,
                    opp.description,
                    opp.url,
                    opp.author,
                    opp.created_at.isoformat(),
                    opp.found_at.isoformat(),
                    opp.budget_min,
                    opp.budget_max,
                    opp.currency,
                    1 if opp.is_hourly else 0,
                    opp.effective_budget,
                    opp.location,
                    1 if opp.is_remote else 0,
                    opp.content_hash,
                    json.dumps(opp.raw_data),
                    opp.status.value,
                ),
            )

    def save_analysis(
        self,
        opp_id: str,
        filter_result: HardFilterResult,
        analysis: Optional[LLMAnalysis] = None,
        score: Optional[ScoringResult] = None,
    ) -> None:
        """Save analysis and scoring results for an opportunity."""
        now_str = datetime.now(timezone.utc).isoformat()
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO analyses (
                    opportunity_id, passed_hard_filters, rejection_reasons_json,
                    match_score, tier, task_type, technical_fit, scope_fit,
                    budget_fit, async_fit, experience_fit, freshness_score,
                    competition_score, risk_level, estimated_hours, recommended_price,
                    why_json, red_flags_json, is_fallback, analyzed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    opp_id,
                    1 if filter_result.passed else 0,
                    json.dumps(filter_result.rejection_reasons),
                    score.match_score if score else None,
                    score.tier.value if score else OpportunityTier.IGNORE.value,
                    analysis.task_type if analysis else None,
                    score.technical_fit if score else None,
                    score.scope_fit if score else None,
                    score.budget_fit if score else None,
                    score.async_fit if score else None,
                    score.experience_fit if score else None,
                    score.freshness_score if score else None,
                    score.competition_score if score else None,
                    analysis.risk_level if analysis else None,
                    score.estimated_hours if score else None,
                    score.recommended_price if score else None,
                    json.dumps(analysis.why) if analysis else "[]",
                    json.dumps(analysis.red_flags) if analysis else "[]",
                    1 if (analysis and analysis.is_fallback) else 0,
                    now_str,
                ),
            )

    def record_notification(
        self,
        opp_id: str,
        channel: str,
        status: str,
        error_message: Optional[str] = None,
    ) -> None:
        """Record notification attempt in database."""
        now_str = datetime.now(timezone.utc).isoformat()
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO notifications (opportunity_id, channel, status, sent_at, error_message)
                VALUES (?, ?, ?, ?, ?)
                """,
                (opp_id, channel, status, now_str, error_message),
            )

    def was_notified(self, opp_id: str, channel: str = "telegram") -> bool:
        """Check if an opportunity was already notified through a given channel."""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM notifications WHERE opportunity_id = ? AND channel = ? AND status = 'SENT' LIMIT 1",
                (opp_id, channel),
            )
            return cursor.fetchone() is not None
        finally:
            conn.close()

    def record_feedback(
        self, opp_id: str, feedback_type: str, notes: Optional[str] = None
    ) -> None:
        """Record user feedback (INTERESTED, REJECTED, SEEN, WON, LOST)."""
        now_str = datetime.now(timezone.utc).isoformat()
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO feedback (opportunity_id, feedback_type, notes, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (opp_id, feedback_type, notes, now_str),
            )
            # Update opportunity status
            conn.execute(
                "UPDATE opportunities SET status = ? WHERE id = ?",
                (feedback_type, opp_id),
            )

    def get_summary_stats(self) -> Dict[str, Any]:
        """Aggregate metrics for CLI summary."""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            total_opps = cursor.execute(
                "SELECT COUNT(*) FROM opportunities"
            ).fetchone()[0]
            passed_filters = cursor.execute(
                "SELECT COUNT(*) FROM analyses WHERE passed_hard_filters = 1"
            ).fetchone()[0]
            rejected_filters = cursor.execute(
                "SELECT COUNT(*) FROM analyses WHERE passed_hard_filters = 0"
            ).fetchone()[0]
            hot_count = cursor.execute(
                "SELECT COUNT(*) FROM analyses WHERE tier = 'HOT'"
            ).fetchone()[0]
            good_count = cursor.execute(
                "SELECT COUNT(*) FROM analyses WHERE tier = 'GOOD'"
            ).fetchone()[0]
            low_count = cursor.execute(
                "SELECT COUNT(*) FROM analyses WHERE tier = 'LOW'"
            ).fetchone()[0]
            ignore_count = cursor.execute(
                "SELECT COUNT(*) FROM analyses WHERE tier = 'IGNORE'"
            ).fetchone()[0]
            sent_notifications = cursor.execute(
                "SELECT COUNT(*) FROM notifications WHERE status = 'SENT'"
            ).fetchone()[0]
            failed_notifications = cursor.execute(
                "SELECT COUNT(*) FROM notifications WHERE status = 'FAILED'"
            ).fetchone()[0]
            last_run_row = cursor.execute(
                "SELECT MAX(found_at) FROM opportunities"
            ).fetchone()[0]

            return {
                "total_opportunities": total_opps,
                "passed_filters": passed_filters,
                "rejected_filters": rejected_filters,
                "tier_hot": hot_count,
                "tier_good": good_count,
                "tier_low": low_count,
                "tier_ignore": ignore_count,
                "sent_notifications": sent_notifications,
                "failed_notifications": failed_notifications,
                "last_found_at": last_run_row,
            }
        finally:
            conn.close()
