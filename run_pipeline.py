import os
import sys
import subprocess

DEFAULT_SHEET_ID = "1XNkTaG02oj76pzxt_TC0-o2ug7zTbpSJl3FK5k2jpXQ"

def run(cmd, env):
    print(f"\n▶ Running: {' '.join(cmd)}")
    subprocess.run(cmd, check=True, env=env)

def main():
    env = os.environ.copy()
    env["GOOGLE_SHEET_ID"] = env.get("GOOGLE_SHEET_ID") or DEFAULT_SHEET_ID

    # 1) scrape (requires CDP Chrome running on 9222)
    run([sys.executable, "tiktok_agent.py"], env)

    # 2) score new rows
    run([sys.executable, "score_agent.py"], env)

    # 3) build the single UI payload
    run([sys.executable, "build_ui_state.py"], env)

    # 4) optional creator enrichment (turn on later)
    # run([sys.executable, "creator_insight_agent.py"], env)

    print("\n✅ Pipeline complete: scrape → score → ui_state")

if __name__ == "__main__":
    main()

