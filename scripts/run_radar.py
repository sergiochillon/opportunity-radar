#!/usr/bin/env python3
"""Main execution script for Opportunity Radar.

Supports both single-run (--once) and continuous daemon mode (--daemon).
"""

import argparse
import logging
from pathlib import Path
import signal
import sys
import time

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from config.settings import load_profile, load_settings
from pipeline.orchestrator import RadarOrchestrator


def setup_logging(log_level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main():
    parser = argparse.ArgumentParser(description="Opportunity Radar Runner")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single execution cycle and exit immediately.",
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Run continuously as a 24/7 background scheduler.",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=None,
        help="Polling interval in minutes (overrides config).",
    )
    args = parser.parse_args()
    if args.interval is not None and args.interval < 1:
        parser.error("--interval must be at least 1 minute.")

    settings = load_settings(BASE_DIR)
    profile = load_profile(BASE_DIR / settings.profile_path)
    setup_logging(settings.log_level)
    logger = logging.getLogger("opportunity_radar")

    orchestrator = RadarOrchestrator(settings, profile)

    if args.once or not args.daemon:
        logger.info("Executing single Opportunity Radar cycle...")
        metrics = orchestrator.run_cycle()
        print("\n=== Cycle Summary ===")
        for k, v in metrics.items():
            print(f"  {k:22}: {v}")
        return

    # Continuous Daemon Mode
    interval_minutes = max(1, args.interval or settings.poll_interval_minutes)
    interval_sec = interval_minutes * 60
    logger.info(
        "Starting Opportunity Radar Daemon (polling every %d minutes / %ds)...",
        interval_minutes,
        interval_sec,
    )

    running = True

    def handle_signal(sig, frame):
        nonlocal running
        logger.info("Received termination signal %s. Shutting down daemon...", sig)
        running = False

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    while running:
        try:
            orchestrator.run_cycle()
        except Exception as e:
            logger.error("Unexpected error during radar execution cycle: %s", e)

        logger.info("Sleeping for %d minutes until next scan...", interval_sec // 60)
        # Sleep in small slices to respond promptly to shutdown signals
        sleep_elapsed = 0
        while running and sleep_elapsed < interval_sec:
            time.sleep(2)
            sleep_elapsed += 2

    logger.info("Opportunity Radar Daemon stopped cleanly.")


if __name__ == "__main__":
    main()
