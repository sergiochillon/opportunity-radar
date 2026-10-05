"""Normalization and budget parsing for Opportunity Radar."""

from datetime import datetime, timezone
import hashlib
import re
from typing import Any, Dict, Optional, Tuple
from pipeline.models import NormalizedOpportunity, OpportunityStatus


CURRENCY_SYMBOLS = {
    "$": "USD",
    "€": "EUR",
    "£": "GBP",
    "USD": "USD",
    "EUR": "EUR",
    "GBP": "GBP",
    "CAD": "CAD",
    "AUD": "AUD",
}


def normalize_content_text(text: str) -> str:
    """Normalize text by stripping URLs, user tags, markdown, and whitespace.

    Enables cross-post detection across subreddits even with slight wording variations.
    """
    if not text:
        return ""
    # Lowercase and remove null characters
    clean = text.replace("\x00", "").lower()
    # Remove URLs
    clean = re.sub(r"https?://\S+|www\.\S+", "", clean)
    # Remove Reddit user tags and markdown links
    clean = re.sub(r"/?u/[a-zA-Z0-9_-]+", "", clean)
    clean = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", clean)
    # Remove common filler tags
    clean = re.sub(
        r"\[(hiring|task|paid|for hire|open)\]", "", clean, flags=re.IGNORECASE
    )
    # Remove all non-alphanumeric except spaces
    clean = re.sub(r"[^a-z0-9\s]", " ", clean)
    # Collapse multiple whitespaces
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


def compute_content_hash(title: str, description: str) -> str:
    """Compute a SHA-256 hash of normalized title and description."""
    norm_title = normalize_content_text(title)
    norm_desc = normalize_content_text(description)
    # Use first 300 characters of description to prevent footer variations from changing hash
    payload = f"{norm_title}|{norm_desc[:300]}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def generate_opportunity_id(source: str, source_id: str) -> str:
    """Generate deterministic unique ID from source and source_id."""
    raw = f"{source.strip().lower()}:{source_id.strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def parse_budget_and_rates(
    text: str,
) -> Tuple[Optional[float], Optional[float], str, bool, Optional[float]]:
    """Parse budget numbers, hourly rates, and currencies from title/description text.

    Returns:
        (budget_min, budget_max, currency, is_hourly, effective_budget)
    """
    if not text:
        return None, None, "USD", False, None

    currency = "USD"
    # Detect currency symbol or code
    for sym, curr in CURRENCY_SYMBOLS.items():
        if sym in text:
            currency = curr
            break

    # Check for hourly indicators
    hourly_match = re.search(
        r"(?:/hr|/hour|per\s+hour|hrly|hourly)", text, re.IGNORECASE
    )
    is_hourly = bool(hourly_match)

    # Regex patterns for price ranges and single values
    # Pattern 1: Range like $15 - $25, 20-30 USD, $20 to $40
    range_pattern = r"(?<![-–\d])(?:[\$€£]?\s*)(\d+(?:\.\d{1,2})?)\s*(?:-|–|to|\/)\s*(?:[\$€£]?\s*)(\d+(?:\.\d{1,2})?)\s*(?:[\$€£]|usd|eur|gbp)?"
    range_match = re.search(range_pattern, text, re.IGNORECASE)

    b_min: Optional[float] = None
    b_max: Optional[float] = None

    if range_match:
        try:
            val1 = float(range_match.group(1))
            val2 = float(range_match.group(2))
            if 1.0 <= val1 <= 50000.0 and 1.0 <= val2 <= 50000.0:
                b_min = min(val1, val2)
                b_max = max(val1, val2)
        except (ValueError, TypeError):
            pass

    # Pattern 2: Single value with currency prefix or suffix, or keywords (budget, presupuesto)
    if b_min is None:
        # Match only when there is an explicit non-negative monetary context
        monetary_context_pattern = (
            r"(?:"
            r"(?:budget|presupuesto)\s*(?:is|:)?\s*[\$€£]?\s*(?<![-–\d])(\d+(?:\.\d{1,2})?)"
            r"|(?<![-–])[\$€£]\s*(?<![-–\d])(\d+(?:\.\d{1,2})?)"
            r"|(?<![-–\d])(\d+(?:\.\d{1,2})?)\s*(?:[\$€£]|usd|eur|gbp|dollars|euros)\b"
            r")"
        )
        match = re.search(monetary_context_pattern, text, re.IGNORECASE)
        if match:
            for g in match.groups():
                if g:
                    try:
                        val = float(g)
                        if 1.0 <= val <= 50000.0:
                            b_min = val
                            b_max = val
                            break
                    except (ValueError, TypeError):
                        pass

    # Calculate effective_budget for unified scoring
    effective_budget: Optional[float] = None
    if b_min is not None:
        avg_val = (b_min + (b_max if b_max is not None else b_min)) / 2.0
        if is_hourly:
            # Assume a typical small project task size of 4 hours
            effective_budget = round(avg_val * 4.0, 2)
        else:
            effective_budget = round(avg_val, 2)

    return b_min, b_max, currency, is_hourly, effective_budget


def normalize_raw_item(
    source: str,
    source_id: str,
    title: str,
    description: str,
    url: str,
    created_at: Optional[datetime] = None,
    author: Optional[str] = None,
    location: Optional[str] = None,
    is_remote: bool = True,
    raw_data: Optional[Dict[str, Any]] = None,
) -> NormalizedOpportunity:
    """Build a fully normalized opportunity object."""
    # Ensure UTC timezone and default datetime if missing
    if created_at is None:
        created_at = datetime.now(timezone.utc)
    elif created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    else:
        created_at = created_at.astimezone(timezone.utc)

    # Clean text, handle None, and strip null bytes
    clean_title = (title or "").replace("\x00", "").strip()
    clean_desc = (description or "").replace("\x00", "").strip()
    clean_url = (url or "").replace("\x00", "").strip()
    clean_author = (
        author.replace("\x00", "").strip() if author else None
    )
    clean_source = (source or "unknown").replace("\x00", "").strip().lower()
    clean_source_id = str(source_id or "").replace("\x00", "").strip()

    # Parse budgets from combined text
    combined_text = f"{clean_title} {clean_desc}"
    b_min, b_max, currency, is_hourly, effective_budget = (
        parse_budget_and_rates(combined_text)
    )

    opp_id = generate_opportunity_id(clean_source, clean_source_id)
    content_hash = compute_content_hash(clean_title, clean_desc)

    return NormalizedOpportunity(
        id=opp_id,
        source=clean_source,
        source_id=clean_source_id,
        title=clean_title,
        description=clean_desc,
        url=clean_url,
        author=clean_author,
        created_at=created_at,
        found_at=datetime.now(timezone.utc),
        budget_min=b_min,
        budget_max=b_max,
        currency=currency,
        is_hourly=is_hourly,
        effective_budget=effective_budget,
        location=location,
        is_remote=is_remote,
        content_hash=content_hash,
        raw_data=raw_data or {},
        status=OpportunityStatus.NEW,
    )
