# auto_loop.py
#
# Runs your TikTok scraper + score agent in a loop.
# Each cycle:
#   1) Runs tiktok_agent.run() to scrape videos into the "videos" sheet
#   2) Runs score_agent.main() to score NEW rows
#   3) Calculates how long the cycle took
#   4) Sleeps just long enough so that a new cycle starts every TARGET_INTERVAL_MINUTES
#
# You stop it manually with CTRL+C in the terminal.

import time
import traceback

from tiktok_agent import run as run_scraper     # from tiktok_agent.py :contentReference[oaicite:0]{index=0}
from score_agent import main as run_scorer      # from score_agent.py :contentReference[oaicite:1]{index=1}

# How often you want a NEW CYCLE to START (in minutes)
# Example:
#   120 = about every 2 hours
#   60  = about every hour
#   30  = pretty aggressive
TARGET_INTERVAL_MINUTES = 120


def run_cycle():
    print("\n==============================")
    print("🚀 New TrendScout cycle starting")
    print("==============================\n")

    # 1) Run the TikTok scraper
    try:
        print("▶ Running TikTok scraper (tiktok_agent.run)...")
        run_scraper()
        print("✅ Scraper finished.")
    except Exception as e:
        print("❌ Scraper crashed:", repr(e))
        traceback.print_exc()

    # 2) Run the score agent
    try:
        print("\n▶ Running score agent (score_agent.main)...")
        run_scorer()
        print("✅ Scoring finished.")
    except Exception as e:
        print("❌ Score agent crashed:", repr(e))
        traceback.print_exc()

    print("\n✅ Cycle complete.")


def main():
    while True:
        start = time.time()

        run_cycle()

        elapsed_minutes = (time.time() - start) / 60.0
        remaining = TARGET_INTERVAL_MINUTES - elapsed_minutes

        if remaining > 0:
            print(
                f"\n⏰ Cycle took {elapsed_minutes:.1f} min. "
                f"Sleeping {remaining:.1f} min before next cycle...\n"
            )
            try:
                time.sleep(remaining * 60)
            except KeyboardInterrupt:
                print("\n🛑 Stopping auto loop by user request (CTRL+C).")
                break
        else:
            # If the cycle took longer than TARGET_INTERVAL_MINUTES,
            # start the next one immediately.
            print(
                f"\n⏰ Cycle took {elapsed_minutes:.1f} min, "
                f"which is longer than target interval ({TARGET_INTERVAL_MINUTES} min)."
            )
            print("Starting next cycle immediately.\n")


if __name__ == "__main__":
    main()

