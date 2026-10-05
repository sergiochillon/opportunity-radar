"""Multi-variable deterministic scoring engine for Opportunity Radar."""

from datetime import datetime, timezone
from typing import Optional
from config.settings import UserProfile
from pipeline.models import (
    LLMAnalysis,
    NormalizedOpportunity,
    OpportunityTier,
    ScoringResult,
)


class ScoringEngine:
    def __init__(self, profile: UserProfile):
        self.profile = profile

    def compute_freshness_score(
        self, created_at: datetime, ref_time: Optional[datetime] = None
    ) -> float:
        """Compute freshness score based on elapsed hours since publication."""
        if ref_time is None:
            ref_time = datetime.now(timezone.utc)

        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        if ref_time.tzinfo is None:
            ref_time = ref_time.replace(tzinfo=timezone.utc)

        age_hours = max(0.0, (ref_time - created_at).total_seconds() / 3600.0)

        for tier in self.profile.freshness.decay_tiers:
            if age_hours <= tier.max_age_hours:
                return tier.score

        return 10.0

    def compute_budget_fit(self, effective_budget: Optional[float]) -> float:
        """Evaluate budget suitability for the user profile."""
        if effective_budget is None:
            # Budget not specified: neutral calibrated score
            return 50.0

        min_b = self.profile.budget.minimum
        pref_min = self.profile.budget.preferred_minimum
        pref_max = self.profile.budget.preferred_maximum

        if effective_budget < min_b:
            # Below absolute minimum (< $10) -> severe penalty
            return max(0.0, (effective_budget / min_b) * 20.0)

        if min_b <= effective_budget < pref_min:
            # Between $10 and $20 -> moderate fit
            ratio = (effective_budget - min_b) / (pref_min - min_b)
            return 30.0 + (ratio * 40.0)  # 30 to 70

        if pref_min <= effective_budget <= pref_max:
            # Sweet spot ($20 - $300) -> optimal
            return 95.0

        # Above preferred maximum (> $300) -> good budget, slight scope awareness
        return 90.0

    def compute_competition_score(self, opp: NormalizedOpportunity) -> float:
        """Infer competition from comments/bids if present in raw_data."""
        num_comments = opp.raw_data.get("num_comments")
        if num_comments is None:
            return 75.0  # Neutral baseline when unknown

        try:
            count = int(num_comments)
            if count <= 2:
                return 100.0
            elif count <= 5:
                return 85.0
            elif count <= 10:
                return 65.0
            elif count <= 20:
                return 40.0
            else:
                return 15.0
        except (ValueError, TypeError):
            return 75.0

    def calculate_score(
        self,
        opp: NormalizedOpportunity,
        analysis: LLMAnalysis,
        ref_time: Optional[datetime] = None,
    ) -> ScoringResult:
        """Calculate weighted composite score and assign opportunity tier."""
        weights = self.profile.scoring_weights

        # 1. Deterministic components in Python
        freshness_score = self.compute_freshness_score(opp.created_at, ref_time)
        budget_fit = self.compute_budget_fit(opp.effective_budget)
        competition_score = self.compute_competition_score(opp)

        # 2. Components evaluated by intelligence (with bounds safety)
        tech_fit = max(0.0, min(100.0, analysis.technical_fit))
        scope_fit = max(0.0, min(100.0, analysis.scope_fit))
        async_fit = max(0.0, min(100.0, analysis.async_fit))
        exp_fit = max(0.0, min(100.0, analysis.experience_fit))

        # 3. Weighted composite sum
        composite_score = (
            (tech_fit * weights.technical_fit)
            + (scope_fit * weights.scope_fit)
            + (budget_fit * weights.budget_fit)
            + (async_fit * weights.async_fit)
            + (exp_fit * weights.experience_fit)
            + (freshness_score * weights.freshness)
            + (competition_score * weights.competition)
        )

        # 4. Critical Hard Guardrails (violation zeroes or slashes score)
        if async_fit < 20.0:
            # Client definitely demands continuous phone calls / zoom
            composite_score = 0.0

        if tech_fit < 20.0:
            # Completely alien tech stack
            composite_score = min(composite_score, 30.0)

        final_score = round(max(0.0, min(100.0, composite_score)), 1)

        # 5. Determine tier based on configurable thresholds
        thresholds = self.profile.score_thresholds
        if final_score >= thresholds.hot:
            tier = OpportunityTier.HOT
        elif final_score >= thresholds.good:
            tier = OpportunityTier.GOOD
        elif final_score >= thresholds.low:
            tier = OpportunityTier.LOW
        else:
            tier = OpportunityTier.IGNORE

        return ScoringResult(
            match_score=final_score,
            tier=tier,
            technical_fit=round(tech_fit, 1),
            scope_fit=round(scope_fit, 1),
            budget_fit=round(budget_fit, 1),
            async_fit=round(async_fit, 1),
            experience_fit=round(exp_fit, 1),
            freshness_score=round(freshness_score, 1),
            competition_score=round(competition_score, 1),
            estimated_hours=analysis.estimated_hours,
            recommended_price=analysis.recommended_price,
            effective_budget=opp.effective_budget,
            breakdown={
                "tech": round(tech_fit * weights.technical_fit, 2),
                "scope": round(scope_fit * weights.scope_fit, 2),
                "budget": round(budget_fit * weights.budget_fit, 2),
                "async": round(async_fit * weights.async_fit, 2),
                "exp": round(exp_fit * weights.experience_fit, 2),
                "freshness": round(freshness_score * weights.freshness, 2),
                "competition": round(
                    competition_score * weights.competition, 2
                ),
            },
        )
