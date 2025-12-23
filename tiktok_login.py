"""
tiktok_login.py

This script attaches to a REAL Google Chrome instance that YOU start manually
with --remote-debugging-port=9222. This avoids Playwright detection issues
and guarantees TikTok login works.

Workflow:

1. Open a NEW terminal window and run:

   /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome \
     --remote-debugging-port=9222 \
     --user-data-dir=/Users/pete/chrome-tiktok-profile

2. Chrome will open. Go to https://www.tiktok.com and log in normally.

3. Once logged in, run in ANOTHER terminal:

   cd /Users/pete/viral_auditor
   source venv/bin/activate
   python tiktok_login.py

4. The script attaches to your REAL Chrome and saves your session to:
   tiktok_state.json

5. Your scraper will now use this session when scraping TikTok.
"""

from playwright.sync_api import sync_playwright

DEBUG_URL = "http://127.0.0.1:9222"
STATE_FILE = "tiktok_state.json"
TIKTOK_URL = "https://www.tiktok.com/"


def main():
    print("=" * 70)
    print(" Connecting to your REAL Chrome @ 9222")
    print("=" * 70)
    print("Make sure you started Chrome like this:")
    print()
    print("  /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome \\")
    print("    --remote-debugging-port=9222 \\")
    print("    --user-data-dir=/Users/pete/chrome-tiktok-profile")
    print()
    print("And make sure you are ALREADY logged into TikTok in that Chrome window.")
    print("=" * 70)
    print()

    with sync_playwright() as p:
        # Attach to Chrome
        browser = p.chromium.connect_over_cdp(DEBUG_URL)

        # Use Chrome’s active browser context
        if browser.contexts:
            context = browser.contexts[0]
        else:
            context = browser.new_context()

        page = context.new_page()
        page.goto(TIKTOK_URL, wait_until="networkidle")

        input("\nWhen TikTok is fully loaded & logged in inside Chrome, press Enter here to save session... ")

        # Save cookies + local storage
        context.storage_state(path=STATE_FILE)
        print(f"\n✅ Saved TikTok session to {STATE_FILE}")

        print("Disconnecting cleanly from Chrome...")
        browser.close()

        print("\n🎉 DONE! Your scraper can now use this TikTok login session.\n")


if __name__ == "__main__":
    main()

