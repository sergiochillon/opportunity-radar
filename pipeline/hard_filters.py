"""Deterministic hard filters for Opportunity Radar.

Applies cheap, zero-cost rules to eliminate non-matching opportunities
before consuming LLM tokens. Includes negative lookbehinds to prevent false positives.
"""

import re
from typing import List, Tuple
from config.settings import UserProfile
from pipeline.models import HardFilterResult, NormalizedOpportunity


class HardFilterEngine:
    def __init__(self, profile: UserProfile):
        self.profile = profile

    def evaluate(self, opp: NormalizedOpportunity) -> HardFilterResult:
        """Run all deterministic filters on the normalized opportunity."""
        rejection_reasons: List[str] = []
        details: dict = {}

        full_text = f"{opp.title} {opp.description}".strip()
        lower_text = full_text.lower()
        title_lower = opp.title.lower()

        # 1. Vendor/Freelancer Offer vs Buyer Intent ([For Hire] vs [Hiring], [OFFER] vs [TASK])
        is_vendor_offer, vendor_reason = self._check_vendor_supply(
            title_lower, opp.raw_data
        )
        if is_vendor_offer:
            rejection_reasons.append(vendor_reason)

        # 2. Unpaid / Volunteer / Equity Only
        if self.profile.constraints.get("no_unpaid", True):
            is_unpaid, unpaid_reason = self._check_unpaid(lower_text)
            if is_unpaid:
                rejection_reasons.append(unpaid_reason)

        # 3. Synchronous Calls / Mandatory Daily Meetings
        if self.profile.constraints.get("no_calls", True):
            is_sync, sync_reason = self._check_mandatory_sync(lower_text)
            if is_sync:
                rejection_reasons.append(sync_reason)

        # 4. Location / On-site / Exclusively restricted countries
        if self.profile.constraints.get("remote_only", True):
            is_local, local_reason = self._check_local_only(lower_text)
            if is_local:
                rejection_reasons.append(local_reason)

        # 5. Seniority Incompatible (8+ years, Principal, Staff Architect)
        is_senior, senior_reason = self._check_excessive_seniority(lower_text)
        if is_senior:
            rejection_reasons.append(senior_reason)

        # 6. Exclusively Frontend / Banned Stacks without backend
        is_frontend_only, fe_reason = self._check_pure_frontend(lower_text)
        if is_frontend_only:
            rejection_reasons.append(fe_reason)

        # 7. Obvious Scams & Spam
        is_scam, scam_reason = self._check_scam_or_spam(lower_text)
        if is_scam:
            rejection_reasons.append(scam_reason)

        passed = len(rejection_reasons) == 0
        return HardFilterResult(
            passed=passed,
            rejection_reasons=rejection_reasons,
            filter_details=details,
        )

    def _check_vendor_supply(
        self, title_lower: str, raw_data: dict
    ) -> Tuple[bool, str]:
        """Detect if the post is a freelancer offering services rather than a client hiring."""
        flair = str(raw_data.get("link_flair_text", "")).lower()

        # Check native flair first
        if flair:
            if "for hire" in flair or "offer" in flair or "freelancer" in flair:
                return True, f"vendor_supply_flair: '{flair}'"
            if "hiring" in flair or "task" in flair or "job" in flair:
                # Explicitly marked as hiring
                return False, ""

        # Check title tags
        if (
            "[for hire]" in title_lower
            or "(for hire)" in title_lower
            or "[offer]" in title_lower
        ):
            return True, "vendor_supply_title_tag"

        # Check seller phrasing at the beginning of title
        if re.search(
            r"^(?:i\s+will|i\s+can|hire\s+me|offering\s+my\s+services|freelance\s+developer\s+available)",
            title_lower,
        ):
            return True, "vendor_supply_phrasing"

        return False, ""

    def _check_unpaid(self, text: str) -> Tuple[bool, str]:
        """Detect unpaid work, volunteer, or equity-only with negative lookbehind."""
        # Check equity/revshare only
        if re.search(
            r"\b(?:equity\s+only|rev(?:enue)?\s*share\s+only|for\s+equity|unpaid\s+intern(?:ship)?|volunteer|for\s+exposure)\b",
            text,
        ):
            # Guard against "no equity only" or "not unpaid"
            if not re.search(r"\b(?:not?|never)\s+unpaid\b", text):
                return True, "unpaid_or_equity_only"

        # Check "unpaid" standalone if not preceded by negative words
        if re.search(r"(?<!no\s)(?<!not\s)(?<!never\s)\bunpaid\b", text):
            return True, "unpaid_work_detected"

        return False, ""

    def _check_mandatory_sync(self, text: str) -> Tuple[bool, str]:
        """Detect mandatory meetings/calls while ignoring 'no meetings', 'calls not required'."""
        # Safe phrases that mention meetings but explicitly negate them
        safe_negations = [
            r"\bno\s+(?:calls?|meetings?|zoom|standups?)\b",
            r"\bcalls?\s+(?:are\s+)?not\s+required\b",
            r"\bmeetings?\s+(?:are\s+)?not\s+required\b",
            r"\bwithout\s+(?:calls?|meetings?|zoom)\b",
            r"\basync(?:hronous)?\s+communication\s+only\b",
            r"\b100%\s+async\b",
        ]
        has_explicit_async_promise = any(
            re.search(pat, text) for pat in safe_negations
        )

        if has_explicit_async_promise:
            # If the client explicitly promises async / no calls, do not reject
            return False, ""

        # Check for mandatory synchronous indicators
        mandatory_patterns = [
            r"\bdaily\s+(?:standups?|syncs?|zoom\s+calls?|meetings?)\b",
            r"\bmandatory\s+(?:calls?|meetings?|zoom)\b",
            r"\bmust\s+be\s+available\s+(?:for|on)\s+(?:daily\s+)?(?:calls?|zoom|voice)\b",
            r"\bphone\s+interview\s+(?:is\s+)?mandatory\b",
            r"\bvoice\s+call\s+required\b",
            r"\bconstant\s+video\s+meetings?\b",
        ]
        for pat in mandatory_patterns:
            if re.search(pat, text):
                return True, f"mandatory_sync_detected: {pat}"

        return False, ""

    def _check_local_only(self, text: str) -> Tuple[bool, str]:
        """Detect on-site only or restrictive citizen requirements."""
        if re.search(
            r"\b(?:on-?site\s+only|in-?person\s+required|must\s+relocate|must\s+work\s+from\s+office)\b",
            text,
        ):
            if not re.search(r"\b(?:not|no)\s+on-?site\b", text):
                return True, "onsite_only_detected"

        if re.search(
            r"\b(?:us\s+citizens?\s+only|us\s+only\s+no\s+exceptions|security\s+clearance\s+required)\b",
            text,
        ):
            return True, "restricted_location_or_clearance"

        return False, ""

    def _check_excessive_seniority(self, text: str) -> Tuple[bool, str]:
        """Detect requirements for 8+ years or principal/staff roles."""
        if re.search(
            r"\b(?:(?:[7-9]|\d{2})\+?\s*(?:years?|yrs)\s*(?:of\s*)?experience)\b",
            text,
        ):
            return True, "seniority_excessive_years"

        if re.search(
            r"\b(?:principal\s+software\s+engineer|staff\s+software\s+engineer|lead\s+architect)\b",
            text,
        ):
            return True, "seniority_excessive_title"

        return False, ""

    def _check_pure_frontend(self, text: str) -> Tuple[bool, str]:
        """Detect pure frontend/mobile projects that have zero backend/Python relevance."""
        frontend_keywords = [
            "react",
            "react.js",
            "next.js",
            "vue",
            "vue.js",
            "angular",
            "figma",
            "flutter",
            "swift",
            "kotlin",
            "ios app",
            "android app",
            "tailwind",
            "frontend only",
            "purely frontend",
            "ui/ux design",
        ]
        backend_keywords = [
            "python",
            "backend",
            "api",
            "rest",
            "fastapi",
            "flask",
            "django",
            "sql",
            "database",
            "scraping",
            "scraper",
            "automation",
            "script",
            "csv",
            "excel",
            "docker",
            "linux",
            "n8n",
            "etl",
            "integration",
            "bot",
        ]

        has_frontend = any(
            re.search(r"\b" + re.escape(kw) + r"\b", text)
            for kw in frontend_keywords
        )
        has_backend = any(
            re.search(r"\b" + re.escape(kw) + r"\b", text)
            for kw in backend_keywords
        )

        # If it has frontend technologies and absolutely ZERO backend relevance, reject
        if has_frontend and not has_backend:
            return True, "purely_frontend_without_backend"

        return False, ""

    def _check_scam_or_spam(self, text: str) -> Tuple[bool, str]:
        """Detect obvious scams, crypto spam, or money flips."""
        scam_patterns = [
            r"\bcash\s*app\s+flip\b",
            r"\bsugar\s+(?:daddy|mommy)\b",
            r"\bpay\s+upfront\s+to\s+start\b",
            r"\bsend\s+deposit\s+first\b",
            r"\bverification\s+code\s+needed\b",
            r"\bwhatsapp\s+me\s+at\s+\+\d+\b",
            r"\bwire\s+transfer\s+advance\b",
        ]
        for pat in scam_patterns:
            if re.search(pat, text):
                return True, f"scam_or_spam_detected: {pat}"

        return False, ""
