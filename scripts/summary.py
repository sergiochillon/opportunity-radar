#!/usr/bin/env python3
"""Summary and metrics viewer for Opportunity Radar."""

from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from config.settings import load_settings
from storage.database import Database


def main():
    settings = load_settings(BASE_DIR)
    db = Database(str(BASE_DIR / settings.database_path))
    stats = db.get_summary_stats()

    print("=" * 55)
    print("           OPPORTUNITY RADAR: METRICS SUMMARY          ")
    print("=" * 55)
    print(f" Database Path         : {settings.database_path}")
    print(f" Last Found Opportunity: {stats.get('last_found_at') or 'None yet'}")
    print("-" * 55)
    print(f" Total Opportunities   : {stats['total_opportunities']}")
    print(f" Passed Hard Filters   : {stats['passed_filters']}")
    print(f" Rejected Hard Filters : {stats['rejected_filters']}")
    print("-" * 55)
    print(" OPPORTUNITY TIERS:")
    print(f"   🔥 HOT  (>= 80 pts) : {stats['tier_hot']}")
    print(f"   ⚡ GOOD (65-79 pts) : {stats['tier_good']}")
    print(f"   📉 LOW  (50-64 pts) : {stats['tier_low']}")
    print(f"   ❌ IGNORE (< 50 pts): {stats['tier_ignore']}")
    print("-" * 55)
    print(" NOTIFICATIONS:")
    print(f"   ✓ Sent Successfully : {stats['sent_notifications']}")
    print(f"   ✗ Failed Attempts   : {stats['failed_notifications']}")
    print("=" * 55)


if __name__ == "__main__":
    main()
