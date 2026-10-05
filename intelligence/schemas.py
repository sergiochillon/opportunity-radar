"""Pydantic schemas for LLM structured output."""

from typing import List
from pydantic import BaseModel, Field


class GeminiAnalysisOutput(BaseModel):
    task_type: str = Field(
        description="Short snake_case description of the task, e.g. python_api_bugfix, web_scraper, automation_script"
    )
    technical_fit: float = Field(
        ge=0.0,
        le=100.0,
        description="Fit with candidate's backend skills (Python, APIs, SQL, scraping, automation). 0 if pure frontend or unknown tech.",
    )
    scope_fit: float = Field(
        ge=0.0,
        le=100.0,
        description="Fit in size: 90-100 for small scripts/bugs (1-8h), 50 for medium (2-3 days), 10 for huge full-stack/SaaS systems.",
    )
    async_fit: float = Field(
        ge=0.0,
        le=100.0,
        description="Fit with asynchronous workflow: 100 if purely async chat/PR/email, 0 if client requires calls/zoom/standups.",
    )
    experience_fit: float = Field(
        ge=0.0,
        le=100.0,
        description="Fit with junior engineer: 90-100 for well-defined small tasks, 30-50 for ambiguous, 0 for senior/staff architect roles.",
    )
    clarity_fit: float = Field(
        ge=0.0,
        le=100.0,
        description="How clear and well-specified are the requirements and deliverables.",
    )
    risk_level: str = Field(
        description="'low', 'medium', or 'high'. Low = simple bug/script. High = ambiguous scope, difficult client, or potential unpaid creep."
    )
    estimated_hours: float = Field(
        ge=0.5,
        le=100.0,
        description="Realistic hours for a junior to complete this task.",
    )
    recommended_price: float = Field(
        ge=10.0,
        le=1000.0,
        description="Recommended fair quote in USD/EUR to propose to the client.",
    )
    why: List[str] = Field(
        description="3 to 5 concise bullet points highlighting why this opportunity matches the candidate."
    )
    red_flags: List[str] = Field(
        default_factory=list,
        description="Any potential risks, ambiguities, or warnings.",
    )
