"""
Multi-channel scheduler for automated content posting.
"""
import argparse
import time
import schedule
import logging
from datetime import datetime
from typing import Dict, List
from src.main import ContentPipeline
from src.utils import list_available_channels
from src.config import settings


logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("Scheduler")


class MultiChannelScheduler:
    """Manages scheduling for multiple Instagram channels."""

    def __init__(self):
        """Initialize the scheduler."""
        self.pipeline = ContentPipeline()
        self.channels = list_available_channels()
        self.posting_history: Dict[str, List[datetime]] = {
            channel: [] for channel in self.channels
        }

    def schedule_channel(self, channel_name: str, posts_per_day: int = 2):
        """
        Schedule posts for a channel.

        Args:
            channel_name: Channel to schedule
            posts_per_day: Number of posts per day
        """
        if channel_name not in self.channels:
            logger.error(f"Channel '{channel_name}' not found")
            return

        logger.info(f"Scheduling {posts_per_day} posts/day for {channel_name}")

        # Distribute posts evenly throughout the day
        # For 2 posts: 9:00 AM and 5:00 PM
        # For 3 posts: 9:00 AM, 2:00 PM, 7:00 PM
        if posts_per_day == 2:
            times = ["09:00", "17:00"]
        elif posts_per_day == 3:
            times = ["09:00", "14:00", "19:00"]
        else:
            # Distribute evenly
            hours = [9 + i * (12 // posts_per_day) for i in range(posts_per_day)]
            times = [f"{hour:02d}:00" for hour in hours]

        for post_time in times:
            schedule.every().day.at(post_time).do(
                self._post_to_channel, channel_name
            )
            logger.info(f"  - Scheduled {channel_name} at {post_time}")

    def schedule_all_channels(self):
        """Schedule all configured channels based on their settings."""
        logger.info("Setting up schedules for all channels...")

        for channel_name in self.channels:
            # Default to 2 posts per day
            # This could be made configurable per channel in channels.yaml
            self.schedule_channel(channel_name, posts_per_day=2)

        logger.info(f"Scheduled {len(self.channels)} channels")

    def _post_to_channel(self, channel_name: str):
        """
        Execute posting for a channel.

        Args:
            channel_name: Channel to post to
        """
        logger.info(f"\n{'='*80}")
        logger.info(f"Executing scheduled post for: {channel_name}")
        logger.info(f"{'='*80}\n")

        try:
            result = self.pipeline.run(channel_name=channel_name, dry_run=False)

            if result.status == "success":
                self.posting_history[channel_name].append(datetime.now())
                logger.info(f"Successfully posted to {channel_name}")
            else:
                logger.error(f"Failed to post to {channel_name}: {result.error_message}")

        except Exception as e:
            logger.error(f"Error posting to {channel_name}: {e}", exc_info=True)

    def run(self, test_mode: bool = False):
        """
        Run the scheduler.

        Args:
            test_mode: If True, run jobs immediately for testing
        """
        if test_mode:
            logger.info("Running in TEST MODE - executing all scheduled jobs once")
            for channel_name in self.channels:
                self._post_to_channel(channel_name)
            return

        logger.info("Starting scheduler... Press Ctrl+C to stop")
        logger.info(f"Monitoring {len(self.channels)} channels")

        try:
            while True:
                schedule.run_pending()
                time.sleep(60)  # Check every minute

        except KeyboardInterrupt:
            logger.info("\nScheduler stopped by user")

    def get_next_runs(self) -> Dict[str, str]:
        """
        Get next scheduled run times for all jobs.

        Returns:
            Dictionary mapping channel names to next run times
        """
        next_runs = {}
        for job in schedule.jobs:
            # Extract channel name from job
            if hasattr(job.job_func, "args") and job.job_func.args:
                channel = job.job_func.args[0]
                next_run = job.next_run.strftime("%Y-%m-%d %H:%M:%S")
                if channel not in next_runs:
                    next_runs[channel] = []
                next_runs[channel].append(next_run)

        return next_runs


def main():
    """Main entry point for scheduler CLI."""
    parser = argparse.ArgumentParser(
        description="Multi-channel Instagram posting scheduler"
    )

    parser.add_argument(
        "--test-mode",
        action="store_true",
        help="Run all scheduled jobs once immediately (for testing)",
    )

    parser.add_argument(
        "--channel",
        type=str,
        help="Schedule only this channel (default: all channels)",
    )

    parser.add_argument(
        "--posts-per-day",
        type=int,
        default=2,
        help="Number of posts per day per channel (default: 2)",
    )

    args = parser.parse_args()

    scheduler = MultiChannelScheduler()

    if args.channel:
        # Schedule specific channel
        scheduler.schedule_channel(args.channel, args.posts_per_day)
    else:
        # Schedule all channels
        scheduler.schedule_all_channels()

    # Show schedule
    next_runs = scheduler.get_next_runs()
    print("\nScheduled posts:")
    print("-" * 80)
    for channel, times in next_runs.items():
        print(f"{channel}:")
        for t in times:
            print(f"  - {t}")
    print("-" * 80)

    # Run scheduler
    scheduler.run(test_mode=args.test_mode)


if __name__ == "__main__":
    main()
