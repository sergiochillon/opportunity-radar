"""Reddit OAuth2 API client for official, zero-cost access."""

import logging
import time
from typing import Any, Dict, List, Optional
import httpx
from config.settings import AppSettings

logger = logging.getLogger("opportunity_radar.collectors.reddit.client")


class RedditClient:
    OAUTH_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
    OAUTH_API_BASE = "https://oauth.reddit.com"

    def __init__(self, settings: AppSettings):
        self.settings = settings
        self.client_id = settings.reddit_client_id
        self.client_secret = settings.reddit_client_secret
        self.user_agent = settings.reddit_user_agent
        self.username = settings.reddit_username
        self.password = settings.reddit_password

        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0.0

    @property
    def is_configured(self) -> bool:
        return bool(
            self.client_id
            and self.client_secret
            and self.username
            and self.password
        )

    def _authenticate(self) -> bool:
        """Authenticate with Reddit using OAuth2 password grant for script applications."""
        if not self.is_configured:
            logger.warning(
                "Reddit credentials not fully configured in settings."
            )
            return False

        headers = {"User-Agent": self.user_agent}
        data = {
            "grant_type": "password",
            "username": self.username,
            "password": self.password,
        }
        auth = (self.client_id, self.client_secret)

        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(
                    self.OAUTH_TOKEN_URL, headers=headers, data=data, auth=auth
                )
                if resp.status_code == 200:
                    token_data = resp.json()
                    self._access_token = token_data.get("access_token")
                    expires_in = token_data.get("expires_in", 3600)
                    self._token_expires_at = time.time() + (expires_in - 300)
                    logger.info(
                        "Successfully authenticated with Reddit OAuth2 API."
                    )
                    return True
                else:
                    logger.error(
                        "Reddit OAuth2 authentication failed (HTTP %d): %s",
                        resp.status_code,
                        resp.text[:200],
                    )
                    return False
        except Exception as e:
            logger.error("Exception during Reddit OAuth2 authentication: %s", e)
            return False

    def _ensure_token(self) -> Optional[str]:
        """Ensure an active, non-expired access token is available."""
        if not self._access_token or time.time() >= self._token_expires_at:
            if not self._authenticate():
                return None
        return self._access_token

    def get_new_listings(
        self, subreddits: str = "forhire+freelance_forhire+slavelabour+pythonjobs", limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Fetch newest listings from specified subreddits using OAuth2 endpoint."""
        token = self._ensure_token()
        if not token:
            logger.warning(
                "Cannot fetch Reddit listings: No valid OAuth2 access token."
            )
            return []

        url = f"{self.OAUTH_API_BASE}/r/{subreddits}/new"
        headers = {
            "User-Agent": self.user_agent,
            "Authorization": f"Bearer {token}",
        }
        params = {"limit": limit}

        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.get(url, headers=headers, params=params)

                # Check rate limit headers
                ratelimit_remaining = resp.headers.get("X-Ratelimit-Remaining")
                ratelimit_reset = resp.headers.get("X-Ratelimit-Reset")
                if ratelimit_remaining is not None:
                    logger.debug(
                        "Reddit Rate Limit: %s remaining, resets in %s seconds",
                        ratelimit_remaining,
                        ratelimit_reset,
                    )

                if resp.status_code == 200:
                    data = resp.json()
                    children = data.get("data", {}).get("children", [])
                    posts = [c.get("data", {}) for c in children if c.get("data")]
                    logger.info(
                        "Fetched %d raw posts from Reddit r/%s",
                        len(posts),
                        subreddits,
                    )
                    return posts
                elif resp.status_code == 401:
                    logger.warning(
                        "Reddit token expired or unauthorized. Invaliding token."
                    )
                    self._access_token = None
                    return []
                elif resp.status_code == 429:
                    logger.warning(
                        "Reddit rate limit hit (HTTP 429). Reset in %s seconds.",
                        ratelimit_reset,
                    )
                    return []
                else:
                    logger.error(
                        "Reddit API query returned HTTP %d: %s",
                        resp.status_code,
                        resp.text[:200],
                    )
                    return []
        except Exception as e:
            logger.error("Exception querying Reddit API: %s", e)
            return []
