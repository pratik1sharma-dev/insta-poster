"""
Standalone feedback service — run alongside the pipeline.

Usage:
    python3 -m src.feedback_service
    python3 -m src.feedback_service --channels wealthcapsules,pagecapsules
"""
import argparse
import logging
import yaml

from src.agents.feedback_loop import FeedbackLoop
from src.config import settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Feedback learning service for insta-poster")
    parser.add_argument(
        "--channels",
        help="Comma-separated channel names (default: all channels in channels.yaml)",
    )
    parser.add_argument(
        "--log-level",
        default=settings.log_level,
        help="Logging level (default: from settings)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if args.channels:
        channels = [c.strip() for c in args.channels.split(",") if c.strip()]
    else:
        with open("src/config/channels.yaml") as f:
            channels = list(yaml.safe_load(f).keys())

    logging.getLogger(__name__).info("Feedback service starting for channels: %s", channels)
    FeedbackLoop().run_forever(channels)


if __name__ == "__main__":
    main()
