"""Gemini LLM client with structured output, safety handling, and graceful fallback."""

import json
import logging
import time
from typing import Optional

from config.settings import AppSettings, UserProfile
from intelligence.fallback import FallbackEstimator
from intelligence.prompts import SYSTEM_PROMPT, build_analysis_prompt
from intelligence.schemas import GeminiAnalysisOutput
from pipeline.models import LLMAnalysis, NormalizedOpportunity

logger = logging.getLogger("opportunity_radar.intelligence")


class OpportunityAnalyzer:
    def __init__(self, settings: AppSettings, profile: UserProfile):
        self.settings = settings
        self.profile = profile
        self.fallback = FallbackEstimator(profile)
        self._client = None
        self._last_call_time = 0.0
        self._min_interval_sec = 2.0  # Safe rate-limiting between LLM calls

        if self.settings.gemini_api_key:
            try:
                from google import genai

                self._client = genai.Client(
                    api_key=self.settings.gemini_api_key
                )
                logger.info("Initialized Google Gemini client successfully.")
            except Exception as e:
                logger.warning(
                    "Failed to initialize google-genai client (%s). Will use heuristic fallback.",
                    e,
                )

    def analyze(self, opp: NormalizedOpportunity) -> LLMAnalysis:
        """Analyze an opportunity using Gemini structured output, falling back if unavailable."""
        if not self._client or not self.settings.gemini_api_key:
            logger.debug(
                "Gemini API key not configured or client inactive. Using heuristic fallback for %s.",
                opp.id,
            )
            return self.fallback.estimate(opp)

        # Enforce gentle rate-limiting interval
        elapsed = time.time() - self._last_call_time
        if elapsed < self._min_interval_sec:
            time.sleep(self._min_interval_sec - elapsed)

        prompt = build_analysis_prompt(opp, self.profile)
        max_retries = 2

        for attempt in range(max_retries):
            try:
                self._last_call_time = time.time()
                from google.genai import types

                config = types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0.2,
                    response_mime_type="application/json",
                    response_schema=GeminiAnalysisOutput,
                    safety_settings=[
                        types.SafetySetting(
                            category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                            threshold=types.HarmBlockThreshold.BLOCK_NONE,
                        ),
                        types.SafetySetting(
                            category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                            threshold=types.HarmBlockThreshold.BLOCK_NONE,
                        ),
                        types.SafetySetting(
                            category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
                            threshold=types.HarmBlockThreshold.BLOCK_NONE,
                        ),
                        types.SafetySetting(
                            category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                            threshold=types.HarmBlockThreshold.BLOCK_NONE,
                        ),
                    ],
                )

                response = self._client.models.generate_content(
                    model=self.settings.gemini_model,
                    contents=prompt,
                    config=config,
                )

                if not response.text:
                    logger.warning(
                        "Empty response from Gemini on %s (attempt %d).",
                        opp.id,
                        attempt + 1,
                    )
                    continue

                raw_json = json.loads(response.text)
                structured = GeminiAnalysisOutput(**raw_json)

                return LLMAnalysis(
                    task_type=structured.task_type,
                    technical_fit=structured.technical_fit,
                    scope_fit=structured.scope_fit,
                    async_fit=structured.async_fit,
                    experience_fit=structured.experience_fit,
                    clarity_fit=structured.clarity_fit,
                    risk_level=structured.risk_level.lower(),
                    estimated_hours=structured.estimated_hours,
                    recommended_price=structured.recommended_price,
                    why=structured.why,
                    red_flags=structured.red_flags,
                    is_fallback=False,
                )

            except Exception as e:
                logger.warning(
                    "Gemini analysis attempt %d failed for %s: %s",
                    attempt + 1,
                    opp.id,
                    e,
                )
                time.sleep(2.0 * (attempt + 1))

        logger.warning(
            "Gemini exhausted retries for %s. Engaging heuristic fallback.",
            opp.id,
        )
        return self.fallback.estimate(opp)
