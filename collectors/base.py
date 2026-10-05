"""Base collector interface for all Opportunity Radar sources."""

from abc import ABC, abstractmethod
import logging
from typing import List
from pipeline.models import NormalizedOpportunity

logger = logging.getLogger("opportunity_radar.collectors")


class BaseCollector(ABC):
    """Abstract base class that all collectors must implement."""

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def fetch_opportunities(self) -> List[NormalizedOpportunity]:
        """Fetch raw listings from the source and return normalized opportunities.

        Must handle source-specific rate limits, network retries, and errors internally.
        """
        pass
