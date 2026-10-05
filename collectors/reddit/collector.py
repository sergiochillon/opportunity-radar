"""Reddit opportunity collector implementation."""

from datetime import datetime, timezone
import logging
from typing import List, Optional

from collectors.base import BaseCollector
from collectors.reddit.client import RedditClient
from config.settings import AppSettings
from pipeline.models import NormalizedOpportunity
from pipeline.normalize import normalize_raw_item

logger = logging.getLogger("opportunity_radar.collectors.reddit")


class RedditCollector(BaseCollector):
    def __init__(
        self,
        settings: AppSettings,
        client: Optional[RedditClient] = None,
        subreddits: str = "forhire+freelance_forhire+slavelabour+pythonjobs",
    ):
        super().__init__(name="reddit")
        self.settings = settings
        self.client = client or RedditClient(settings)
        self.subreddits = subreddits

    def fetch_opportunities(self) -> List[NormalizedOpportunity]:
        """Fetch posts from Reddit, normalizing each into a NormalizedOpportunity."""
        if not self.client.is_configured:
            if self.settings.is_production:
                logger.error(
                    "CRITICAL: Reddit credentials are not configured in production mode!"
                )
            else:
                logger.warning(
                    "Reddit credentials missing. Configure .env with REDDIT_CLIENT_ID etc."
                )
            return []

        raw_posts = self.client.get_new_listings(subreddits=self.subreddits)
        opportunities: List[NormalizedOpportunity] = []

        for p in raw_posts:
            post_id = p.get("id")
            title = p.get("title", "")
            selftext = p.get("selftext", "")
            permalink = p.get("permalink", "")
            author = p.get("author")
            created_utc = p.get("created_utc")
            link_flair = p.get("link_flair_text")
            num_comments = p.get("num_comments", 0)
            subreddit = p.get("subreddit", "")

            if not post_id or not title:
                continue

            # Build direct URL
            url = (
                f"https://reddit.com{permalink}"
                if permalink
                else f"https://reddit.com/comments/{post_id}"
            )

            # Convert created_utc to datetime UTC
            if created_utc:
                try:
                    created_at = datetime.fromtimestamp(
                        float(created_utc), tz=timezone.utc
                    )
                except Exception:
                    created_at = datetime.now(timezone.utc)
            else:
                created_at = datetime.now(timezone.utc)

            raw_metadata = {
                "link_flair_text": link_flair,
                "num_comments": num_comments,
                "subreddit": subreddit,
                "ups": p.get("ups", 0),
            }

            norm_item = normalize_raw_item(
                source="reddit",
                source_id=post_id,
                title=title,
                description=selftext,
                url=url,
                created_at=created_at,
                author=author,
                is_remote=True,
                raw_data=raw_metadata,
            )
            opportunities.append(norm_item)

        logger.info(
            "Reddit collector successfully processed %d opportunities.",
            len(opportunities),
        )
        return opportunities
