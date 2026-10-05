"""Settings and Profile configuration for Opportunity Radar."""

from pathlib import Path
from typing import Any, Dict, List, Optional
import os
import yaml
from pydantic import BaseModel, Field


def _load_env_file(filepath: Path) -> Dict[str, str]:
    """Parse a simple .env file without external dependencies."""
    env_vars: Dict[str, str] = {}
    if not filepath.exists() or not filepath.is_file():
        return env_vars

    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "=" in stripped:
                key, val = stripped.split("=", 1)
                key = key.strip()
                val = val.strip().strip("'\"")
                env_vars[key] = val
    return env_vars


class FreshnessDecayTier(BaseModel):
    max_age_hours: float
    score: float


class FreshnessConfig(BaseModel):
    max_age_hours: float = 48.0
    decay_tiers: List[FreshnessDecayTier] = Field(
        default_factory=lambda: [
            FreshnessDecayTier(max_age_hours=2.0, score=100.0),
            FreshnessDecayTier(max_age_hours=6.0, score=85.0),
            FreshnessDecayTier(max_age_hours=12.0, score=70.0),
            FreshnessDecayTier(max_age_hours=24.0, score=50.0),
            FreshnessDecayTier(max_age_hours=48.0, score=20.0),
        ]
    )


class ScoringWeights(BaseModel):
    technical_fit: float = 0.25
    scope_fit: float = 0.20
    budget_fit: float = 0.15
    async_fit: float = 0.15
    experience_fit: float = 0.10
    freshness: float = 0.10
    competition: float = 0.05


class ScoreThresholds(BaseModel):
    hot: float = 80.0
    good: float = 65.0
    low: float = 50.0


class BudgetConfig(BaseModel):
    minimum: float = 10.0
    preferred_minimum: float = 20.0
    preferred_maximum: float = 300.0


class UserProfile(BaseModel):
    skills: List[str] = Field(default_factory=list)
    preferred_tasks: List[str] = Field(default_factory=list)
    avoid: List[str] = Field(default_factory=list)
    constraints: Dict[str, bool] = Field(default_factory=dict)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    scoring_weights: ScoringWeights = Field(default_factory=ScoringWeights)
    score_thresholds: ScoreThresholds = Field(default_factory=ScoreThresholds)
    freshness: FreshnessConfig = Field(default_factory=FreshnessConfig)


class AppSettings(BaseModel):
    environment: str = "development"
    log_level: str = "INFO"

    # Telegram (sensitive bot token excluded from string representations)
    telegram_bot_token: Optional[str] = Field(default=None, repr=False)
    telegram_chat_id: Optional[str] = None

    # Gemini (sensitive API key excluded from string representations)
    gemini_api_key: Optional[str] = Field(default=None, repr=False)
    gemini_model: str = "gemini-2.5-flash"

    # Reddit (sensitive credentials excluded from string representations)
    reddit_client_id: Optional[str] = None
    reddit_client_secret: Optional[str] = Field(default=None, repr=False)
    reddit_user_agent: str = "OpportunityRadar/1.0 (personal use)"
    reddit_username: Optional[str] = None
    reddit_password: Optional[str] = Field(default=None, repr=False)

    # GitHub (sensitive PAT excluded from string representations)
    github_pat: Optional[str] = Field(default=None, repr=False)

    # Storage & Profile Paths
    database_path: str = "data/radar.db"
    profile_path: str = "config/profile.yaml"

    # Scheduler
    poll_interval_minutes: int = 15

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @property
    def has_telegram(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)

    @property
    def has_gemini(self) -> bool:
        return bool(self.gemini_api_key)

    @property
    def has_reddit_auth(self) -> bool:
        return bool(
            self.reddit_client_id
            and self.reddit_client_secret
            and self.reddit_username
            and self.reddit_password
        )


def load_settings(base_dir: Optional[Path] = None) -> AppSettings:
    """Load settings from .env file and environment variables."""
    if base_dir is None:
        base_dir = Path(__file__).resolve().parent.parent

    env_file = base_dir / ".env"
    file_vars = _load_env_file(env_file)

    def get_var(key: str, default: Any = None) -> Any:
        return os.environ.get(key, file_vars.get(key, default))

    # Safe parsing of poll interval
    raw_poll = get_var("POLL_INTERVAL_MINUTES", 15)
    try:
        poll_int = int(raw_poll)
        poll_interval = poll_int if poll_int > 0 else 15
    except (ValueError, TypeError):
        poll_interval = 15

    return AppSettings(
        environment=str(get_var("ENVIRONMENT", "development")),
        log_level=str(get_var("LOG_LEVEL", "INFO")),
        telegram_bot_token=get_var("TELEGRAM_BOT_TOKEN") or None,
        telegram_chat_id=get_var("TELEGRAM_CHAT_ID") or None,
        gemini_api_key=get_var("GEMINI_API_KEY") or None,
        gemini_model=str(get_var("GEMINI_MODEL", "gemini-2.5-flash")),
        reddit_client_id=get_var("REDDIT_CLIENT_ID") or None,
        reddit_client_secret=get_var("REDDIT_CLIENT_SECRET") or None,
        reddit_user_agent=str(
            get_var("REDDIT_USER_AGENT", "OpportunityRadar/1.0 (personal use)")
        ),
        reddit_username=get_var("REDDIT_USERNAME") or None,
        reddit_password=get_var("REDDIT_PASSWORD") or None,
        github_pat=get_var("GITHUB_PAT") or None,
        database_path=str(get_var("DATABASE_PATH", "data/radar.db")),
        profile_path=str(get_var("PROFILE_PATH", "config/profile.yaml")),
        poll_interval_minutes=poll_interval,
    )


def load_profile(profile_path: Path) -> UserProfile:
    """Load user profile YAML."""
    if not profile_path.exists():
        return UserProfile()

    try:
        with open(profile_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception:
        return UserProfile()

    if not isinstance(data, dict):
        return UserProfile()

    return UserProfile(**data)
