"""Data models for Opportunity Radar pipeline."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class OpportunityStatus(str, Enum):
    NEW = "NEW"
    SEEN = "SEEN"
    INTERESTED = "INTERESTED"
    REJECTED = "REJECTED"
    APPLIED = "APPLIED"
    WON = "WON"
    LOST = "LOST"


class OpportunityTier(str, Enum):
    HOT = "HOT"
    GOOD = "GOOD"
    LOW = "LOW"
    IGNORE = "IGNORE"


class NormalizedOpportunity(BaseModel):
    id: str  # Unique hash: sha256(f"{source}:{source_id}")
    source: str
    source_id: str
    title: str
    description: str
    url: str
    author: Optional[str] = None
    created_at: datetime
    found_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    currency: str = "USD"
    is_hourly: bool = False
    effective_budget: Optional[float] = None
    location: Optional[str] = None
    is_remote: bool = True
    content_hash: str  # Normalized text hash for cross-post deduplication
    raw_data: Dict[str, Any] = Field(default_factory=dict)
    status: OpportunityStatus = OpportunityStatus.NEW


class HardFilterResult(BaseModel):
    passed: bool
    rejection_reasons: List[str] = Field(default_factory=list)
    filter_details: Dict[str, Any] = Field(default_factory=dict)


class LLMAnalysis(BaseModel):
    task_type: str = "unclassified"
    technical_fit: float = Field(default=50.0, ge=0.0, le=100.0)
    scope_fit: float = Field(default=50.0, ge=0.0, le=100.0)
    async_fit: float = Field(default=50.0, ge=0.0, le=100.0)
    experience_fit: float = Field(default=50.0, ge=0.0, le=100.0)
    clarity_fit: float = Field(default=50.0, ge=0.0, le=100.0)
    risk_level: str = "medium"  # low, medium, high
    estimated_hours: float = 4.0
    recommended_price: float = 40.0
    why: List[str] = Field(default_factory=list)
    red_flags: List[str] = Field(default_factory=list)
    is_fallback: bool = False


class ScoringResult(BaseModel):
    match_score: float = Field(ge=0.0, le=100.0)
    tier: OpportunityTier
    technical_fit: float
    scope_fit: float
    budget_fit: float
    async_fit: float
    experience_fit: float
    freshness_score: float
    competition_score: float
    estimated_hours: float
    recommended_price: float
    effective_budget: Optional[float] = None
    breakdown: Dict[str, float] = Field(default_factory=dict)


class ProcessedOpportunity(BaseModel):
    opportunity: NormalizedOpportunity
    filter_result: HardFilterResult
    analysis: Optional[LLMAnalysis] = None
    score: Optional[ScoringResult] = None
