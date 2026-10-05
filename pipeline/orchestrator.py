"""Core pipeline orchestrator for Opportunity Radar."""

import logging
import time
from typing import Dict, List, Optional

from collectors.base import BaseCollector
from collectors.reddit.collector import RedditCollector
from config.settings import AppSettings, UserProfile
from intelligence.llm_client import OpportunityAnalyzer
from notifications.telegram import TelegramNotifier
from pipeline.deduplicate import Deduplicator
from pipeline.hard_filters import HardFilterEngine
from pipeline.models import (
    HardFilterResult,
    NormalizedOpportunity,
    OpportunityTier,
    ProcessedOpportunity,
)
from pipeline.ranking import rank_opportunities
from pipeline.scoring import ScoringEngine
from storage.database import Database

logger = logging.getLogger("opportunity_radar.orchestrator")


class RadarOrchestrator:
    def __init__(
        self,
        settings: AppSettings,
        profile: UserProfile,
        db: Optional[Database] = None,
        collectors: Optional[List[BaseCollector]] = None,
    ):
        self.settings = settings
        self.profile = profile
        self.db = db or Database(settings.database_path)
        self.deduplicator = Deduplicator(self.db)
        self.hard_filters = HardFilterEngine(profile)
        self.analyzer = OpportunityAnalyzer(settings, profile)
        self.scorer = ScoringEngine(profile)
        self.notifier = TelegramNotifier(settings, self.db)

        # Default collectors
        if collectors is not None:
            self.collectors = collectors
        else:
            self.collectors = [RedditCollector(settings)]

    def run_cycle(self) -> Dict[str, int]:
        """Execute one complete cycle of gathering, filtering, analyzing, scoring and notifying."""
        start_time = time.time()
        logger.info("=== Starting Opportunity Radar Cycle ===")

        metrics = {
            "collected": 0,
            "duplicates": 0,
            "rejected_hard_filters": 0,
            "analyzed_llm": 0,
            "tier_hot": 0,
            "tier_good": 0,
            "notified": 0,
        }

        # 1. Fetch from all registered collectors
        all_opportunities: List[NormalizedOpportunity] = []
        for collector in self.collectors:
            try:
                opps = collector.fetch_opportunities()
                logger.info(
                    "Collector '%s' retrieved %d items.", collector.name, len(opps)
                )
                all_opportunities.extend(opps)
            except Exception as e:
                logger.error(
                    "Error executing collector '%s': %s", collector.name, e
                )

        metrics["collected"] = len(all_opportunities)

        processed_items: List[ProcessedOpportunity] = []

        # 2. Process each opportunity through pipeline
        for opp in all_opportunities:
            try:
                # Check deduplication
                is_dup, dup_reason = self.deduplicator.is_duplicate(opp)
                if is_dup:
                    logger.debug("Skipping duplicate %s (%s)", opp.id, dup_reason)
                    metrics["duplicates"] += 1
                    continue

                # Save opportunity record
                self.db.save_opportunity(opp)

                # Deterministic Hard Filters
                filter_res = self.hard_filters.evaluate(opp)
                if not filter_res.passed:
                    logger.debug(
                        "Opportunity %s rejected by hard filters: %s",
                        opp.id,
                        filter_res.rejection_reasons,
                    )
                    metrics["rejected_hard_filters"] += 1
                    self.db.save_analysis(opp.id, filter_res)
                    continue

                # Candidate passed hard filters -> Evaluate with LLM/Fallback
                logger.info("Evaluating candidate opportunity %s with LLM...", opp.id)
                metrics["analyzed_llm"] += 1

                analysis = self.analyzer.analyze(opp)
                score = self.scorer.calculate_score(opp, analysis)

                # Persist analysis and score
                self.db.save_analysis(opp.id, filter_res, analysis, score)

                processed_item = ProcessedOpportunity(
                    opportunity=opp,
                    filter_result=filter_res,
                    analysis=analysis,
                    score=score,
                )
                processed_items.append(processed_item)

                if score.tier == OpportunityTier.HOT:
                    metrics["tier_hot"] += 1
                elif score.tier == OpportunityTier.GOOD:
                    metrics["tier_good"] += 1
            except Exception as e:
                logger.error(
                    "Unexpected error processing opportunity '%s': %s",
                    getattr(opp, "id", "unknown"),
                    e,
                )

        # 3. Rank notifiable candidates
        ranked = rank_opportunities(processed_items)

        # 4. Dispatch Telegram notifications for HOT and GOOD
        for item in ranked:
            if item.score and item.score.tier in (
                OpportunityTier.HOT,
                OpportunityTier.GOOD,
            ):
                sent = self.notifier.send_notification(item)
                if sent:
                    metrics["notified"] += 1

        duration = time.time() - start_time
        logger.info(
            "=== Cycle Finished in %.2fs: %d collected, %d dups, %d rejected, %d analyzed, %d notified ===",
            duration,
            metrics["collected"],
            metrics["duplicates"],
            metrics["rejected_hard_filters"],
            metrics["analyzed_llm"],
            metrics["notified"],
        )
        return metrics
