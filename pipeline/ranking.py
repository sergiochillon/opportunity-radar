"""Ranking and tier assignment utilities."""

from typing import List
from pipeline.models import OpportunityTier, ProcessedOpportunity


def rank_opportunities(
    items: List[ProcessedOpportunity],
) -> List[ProcessedOpportunity]:
    """Sort processed opportunities by match_score descending."""
    return sorted(
        items,
        key=lambda x: (
            x.score.match_score if x.score else -1.0,
            x.opportunity.created_at.timestamp(),
        ),
        reverse=True,
    )


def filter_notifiable_opportunities(
    items: List[ProcessedOpportunity],
) -> List[ProcessedOpportunity]:
    """Filter opportunities that meet HOT or GOOD threshold."""
    return [
        item
        for item in items
        if item.score
        and item.score.tier in (OpportunityTier.HOT, OpportunityTier.GOOD)
    ]
