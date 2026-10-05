"""Telegram notification dispatcher for Opportunity Radar."""

import html
import logging
from typing import Optional
import httpx
from config.settings import AppSettings
from pipeline.models import OpportunityTier, ProcessedOpportunity
from storage.database import Database

logger = logging.getLogger("opportunity_radar.notifications")


class TelegramNotifier:
    def __init__(self, settings: AppSettings, db: Database):
        self.settings = settings
        self.db = db
        self.bot_token = settings.telegram_bot_token
        self.chat_id = settings.telegram_chat_id
        self.base_url = (
            f"https://api.telegram.org/bot{self.bot_token}"
            if self.bot_token
            else None
        )

    def is_configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def _sanitize_token(self, text: str) -> str:
        """Redact sensitive bot token from logs and database error messages."""
        if self.bot_token and self.bot_token in text:
            return text.replace(self.bot_token, "[REDACTED_BOT_TOKEN]")
        return text

    def format_message(self, item: ProcessedOpportunity) -> str:
        """Format an opportunity into clean, structured Telegram HTML."""
        opp = item.opportunity
        score = item.score
        analysis = item.analysis

        tier_icon = (
            "🔥 HOT"
            if score and score.tier == OpportunityTier.HOT
            else "⚡ GOOD"
        )
        match_score = score.match_score if score else 0.0

        # Safe budget formatting
        if opp.budget_min is not None and opp.budget_max is not None:
            if opp.budget_min == opp.budget_max:
                budget_str = f"${opp.budget_min:.0f}"
            else:
                budget_str = f"${opp.budget_min:.0f}-${opp.budget_max:.0f}"
            if opp.is_hourly:
                budget_str += "/hr"
        elif opp.effective_budget is not None:
            budget_str = f"${opp.effective_budget:.0f}"
        else:
            budget_str = "Negotiable / Open"

        est_hours = score.estimated_hours if score else 3.0
        rec_price = score.recommended_price if score else 40.0

        # Clean null characters and bound text lengths to prevent Telegram message overflows
        raw_title = (opp.title or "").replace("\x00", "").strip()
        title_bounded = (raw_title[:280] + "...") if len(raw_title) > 280 else raw_title
        safe_title = html.escape(title_bounded)

        safe_source = html.escape(
            (opp.source or "RADAR").replace("\x00", "").strip().upper()
        )
        task_type_raw = (
            analysis.task_type.replace("_", " ").title()
            if analysis
            else "Backend Task"
        )
        safe_task_type = html.escape(task_type_raw.replace("\x00", ""))

        lines = [
            f"<b>{tier_icon} | MATCH: {match_score:.0f}/100</b>",
            f"📌 <b>[{safe_source}]</b> {safe_task_type}",
            f"📝 <i>{safe_title}</i>",
            "",
            f"💰 <b>Budget:</b> {budget_str}",
            f"⏱ <b>Est. Time:</b> ~{est_hours:.1f}h | <b>Quote:</b> ${rec_price:.0f}",
            "🌍 <b>Modality:</b> 100% Remote | 📡 <b>Async:</b> Yes",
            "",
            "<b>POR QUÉ ENCAJA:</b>",
        ]

        # Why bullets (bounded)
        why_list = (
            analysis.why if analysis and analysis.why else ["Matches profile"]
        )
        for bullet in why_list[:4]:
            clean_bullet = str(bullet).replace("\x00", "").strip()
            bullet_bounded = (
                clean_bullet[:150] + "..."
                if len(clean_bullet) > 150
                else clean_bullet
            )
            lines.append(f"✓ {html.escape(bullet_bounded)}")

        # Red flags / Warnings if any (bounded)
        if analysis and analysis.red_flags:
            lines.append("")
            lines.append("⚠️ <b>ALERTAS / RIESGOS:</b>")
            for flag in analysis.red_flags[:3]:
                clean_flag = str(flag).replace("\x00", "").strip()
                flag_bounded = (
                    clean_flag[:150] + "..."
                    if len(clean_flag) > 150
                    else clean_flag
                )
                lines.append(f"• {html.escape(flag_bounded)}")

        lines.append("")
        # Enforce Telegram allowed protocols (http, https, tg) to prevent parse errors
        raw_url = (opp.url or "").replace("\x00", "").strip()
        if raw_url.startswith(("http://", "https://", "tg://")):
            safe_url = html.escape(raw_url, quote=True)
            lines.append(f'🔗 <a href="{safe_url}"><b>[VER OFERTA ORIGINAL]</b></a>')
        elif raw_url:
            safe_url = html.escape(raw_url)
            lines.append(f"🔗 <b>Enlace:</b> {safe_url}")

        return "\n".join(lines)

    def send_notification(self, item: ProcessedOpportunity) -> bool:
        """Send notification to Telegram if not already notified."""
        opp_id = item.opportunity.id

        if not self.is_configured():
            logger.info(
                "Telegram not configured. Skipping notification dispatch for %s.",
                opp_id,
            )
            return False

        if self.db.was_notified(opp_id, "telegram"):
            logger.debug(
                "Opportunity %s was already notified. Skipping.", opp_id
            )
            return False

        message_text = self.format_message(item)
        endpoint = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": message_text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        }

        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(endpoint, json=payload)
                if resp.status_code == 200:
                    self.db.record_notification(opp_id, "telegram", "SENT")
                    logger.info(
                        "Successfully sent Telegram notification for %s.", opp_id
                    )
                    return True
                else:
                    error_msg = self._sanitize_token(
                        f"HTTP {resp.status_code}: {resp.text[:200]}"
                    )
                    self.db.record_notification(
                        opp_id, "telegram", "FAILED", error_message=error_msg
                    )
                    logger.error(
                        "Telegram sendMessage failed for %s: %s",
                        opp_id,
                        error_msg,
                    )
                    return False
        except Exception as e:
            error_msg = self._sanitize_token(str(e))
            self.db.record_notification(
                opp_id, "telegram", "FAILED", error_message=error_msg
            )
            logger.error(
                "Exception during Telegram dispatch for %s: %s", opp_id, error_msg
            )
            return False
