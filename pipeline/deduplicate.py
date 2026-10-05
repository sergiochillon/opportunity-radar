"""Deduplication logic for Opportunity Radar."""

from typing import Optional, Tuple
from pipeline.models import NormalizedOpportunity
from storage.database import Database


class Deduplicator:
    def __init__(self, db: Database, author_window_hours: float = 6.0):
        self.db = db
        self.author_window_hours = author_window_hours

    def is_duplicate(
        self, opp: NormalizedOpportunity
    ) -> Tuple[bool, Optional[str]]:
        """Check if an opportunity is already known or syndicated.

        Returns:
            (is_dup, reason)
        """
        # 1. Exact match on source and source_id
        if self.db.opportunity_exists(opp.source, opp.source_id):
            return True, f"duplicate_source_id: {opp.source}:{opp.source_id}"

        # 2. Canonical URL match
        if opp.url and self.db.opportunity_exists(
            opp.source, opp.source_id, url=opp.url
        ):
            return True, f"duplicate_url: {opp.url}"

        # 3. Normalized Content Hash match (cross-subreddit posts)
        if opp.content_hash and self.db.opportunity_exists(
            opp.source, opp.source_id, content_hash=opp.content_hash
        ):
            return (
                True,
                f"duplicate_content_hash: cross-post match {opp.content_hash[:8]}",
            )

        # 4. Author + Time Window match (< 6 hours)
        if opp.author and self.db.is_recent_crosspost(
            opp.author, opp.created_at, window_hours=self.author_window_hours
        ):
            return (
                True,
                f"duplicate_author_window: {opp.author} posted within {self.author_window_hours}h",
            )

        return False, None
