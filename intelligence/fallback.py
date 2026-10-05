"""Deterministic heuristic fallback when LLM is unavailable or quota is exceeded."""

import re
from typing import List
from config.settings import UserProfile
from pipeline.models import LLMAnalysis, NormalizedOpportunity


class FallbackEstimator:
    """Heuristic estimator that provides an analysis without external API dependencies."""

    def __init__(self, profile: UserProfile):
        self.profile = profile

    def estimate(self, opp: NormalizedOpportunity) -> LLMAnalysis:
        full_text = f"{opp.title} {opp.description}".lower()

        # 1. Technical Fit calculation
        matched_skills: List[str] = []
        for skill in self.profile.skills:
            if re.search(r"\b" + re.escape(skill.lower()) + r"\b", full_text):
                matched_skills.append(skill)

        if matched_skills:
            # Base 60 + 10 per matched skill up to 95
            tech_fit = min(95.0, 60.0 + (len(matched_skills) * 10.0))
        else:
            tech_fit = 40.0

        # 2. Scope Fit calculation
        small_scope_words = [
            "quick",
            "small",
            "simple",
            "fix",
            "bug",
            "script",
            "scraper",
            "endpoint",
            "csv",
            "automate",
            "bot",
        ]
        large_scope_words = [
            "full stack",
            "saas",
            "entire system",
            "complex architecture",
            "production platform",
        ]

        small_hits = sum(
            1
            for w in small_scope_words
            if re.search(r"\b" + re.escape(w) + r"\b", full_text)
        )
        large_hits = sum(
            1
            for w in large_scope_words
            if re.search(r"\b" + re.escape(w) + r"\b", full_text)
        )

        if large_hits > 0:
            scope_fit = 35.0
            est_hours = 16.0
        elif small_hits >= 2:
            scope_fit = 90.0
            est_hours = 2.5
        else:
            scope_fit = 70.0
            est_hours = 4.0

        # 3. Async & Experience Fit
        async_fit = 90.0
        experience_fit = 80.0

        # 4. Recommended Price
        if opp.effective_budget:
            recommended_price = max(20.0, opp.effective_budget)
        else:
            recommended_price = 45.0

        why_bullets = [
            f"Matched skills: {', '.join(matched_skills[:4])}"
            if matched_skills
            else "Backend keywords found",
            "Estimated scope: small/medium task",
            "Async compatible text format",
            "[Heuristic Fallback: evaluated via rule engine]",
        ]

        red_flags: List[str] = []
        if not opp.effective_budget:
            red_flags.append("Budget not explicitly stated by client")

        return LLMAnalysis(
            task_type="heuristic_backend_task",
            technical_fit=tech_fit,
            scope_fit=scope_fit,
            async_fit=async_fit,
            experience_fit=experience_fit,
            clarity_fit=75.0,
            risk_level="low" if scope_fit > 80 else "medium",
            estimated_hours=est_hours,
            recommended_price=recommended_price,
            why=why_bullets,
            red_flags=red_flags,
            is_fallback=True,
        )
