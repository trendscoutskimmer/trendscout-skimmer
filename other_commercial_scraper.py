# other_commercial_scraper.py
#
# TikTok "Other commercial content" firehose scraper (NO API).
#
# FLOW:
#   1) You run this script.
#   2) It opens: https://library.tiktok.com/other-commercial-content
#   3) YOU manually:
#        - Set "Ad target country" = "All countries"
#        - Set the date range how you want
#   4) You press ENTER in the terminal.
#   5) Script:
#        - Does NOT use the search box at all
#        - Scrolls the page to load lots of results
#        - Collects TikTok video URLs & library detail URLs
#        - Appends NEW URLs into the "ads" worksheet in your Google Sheet.
#
# Sheet: 1XNkTaG02oj76pzxt_TC0-o2ug7zTbpSJl3FK5k2jpXQ
# Worksheet "ads" schema:
#   A: timestamp_utc
#   B: search_term   (here we store a label like "other_commercial_bulk")
#   C: url           (video or detail URL)
#   D: source        ("other_commercial")

from datetime import datetime
import time
from urllib.parse import urljoin

import gspread
from google.oauth2.service_account import Credentials
from playwright.sync_api import (
    sync_playwright,
    TimeoutError as PlaywrightTimeoutError,
)

# ───────────────────────── CONFIG ─────────────────────────

SERVICE_ACCOUNT_FILE = "service_account.json"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SHEET_ID = "1XNkTaG02oj76pzxt_TC0-o2ug7zTbpSJl3FK5k2jpXQ"

ADS_SHEET_NAME = "ads"

OTHER_COMMERCIAL_URL = "https://library.tiktok.com/other-commercial-content"

SCROLL_PASSES = 20       # increase/decrease depending how deep you want to go
SCROLL_SLEEP_MS = 1500
INITIAL_WAIT_MS = 3000


# ─────────────── GOOGLE SHEETS HELPERS ───────────────

def get_sheets_client():
    creds = Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    return gspread.authorize(creds)


def get_ads_sheet():
    client = get_sheets_client()
    wb = client.open_by_key(SHEET_ID)
    try:
        ws = wb.worksheet(ADS_SHEET_NAME)
    except gspread.WorksheetNotFound:
        ws = wb.add_worksheet(title=ADS_SHEET_NAME, rows=2000, cols=10)
        ws.append_row(
            ["timestamp_utc", "search_term", "url", "source"],
            value_input_option="RAW",
        )
    return ws


def get_existing_urls(ads_ws):
    urls = ads_ws.col_values(3)[1:]  # column C after header
    existing = set(u.strip() for u in urls if u.strip())
    print(f"[OTHER] Found {len(existing)} existing URLs in sheet.")
    return existing


# ─────────────── BROWSER SETUP ───────────────

def open_other_commercial_page(p):
    """
    Launch a fresh Chromium window and open the Other Commercial Content page.
    You set filters manually; we never touch country or date.
    """
    browser = p.chromium.launch(headless=False, slow_mo=80)
    context = browser.new_context(
        viewport={"width": 1400, "height": 800},  # keep desktop layout
    )
    page = context.new_page()

    try:
        page.goto(OTHER_COMMERCIAL_URL, wait_until="domcontentloaded", timeout=60000)
    except PlaywrightTimeoutError:
        print("[OTHER] ⚠️ Timeout loading Other commercial content page, continuing anyway.")

    print("\n[OTHER] IMPORTANT SETUP (do this in the browser that just opened):")
    print("  • Set 'Ad target country' = 'All countries'.")
    print("  • Set the date range however you want.")
    print("  • Make sure the page is on the 'Other commercial content' tab.")
    input("[OTHER] When you're done setting filters, press ENTER here to start scraping... ")

    return browser, page


# ─────────────── SCRAPE HELPERS ───────────────

def collect_urls_from_page(page):
    """
    From the current Other Commercial Content page, collect:
      - TikTok video URLs
      - Library detail URLs for other commercial content
    """
    anchors = page.query_selector_all("a")
    urls = set()

    for a in anchors:
        href = a.get_attribute("href")
        if not href:
            continue
        href = href.strip()
        if not href:
            continue

        # Normalize relative URLs
        if href.startswith("/"):
            href = urljoin(OTHER_COMMERCIAL_URL, href)

        lower = href.lower()

        # Direct TikTok video links
        if "tiktok.com" in lower and "/video/" in lower:
            urls.add(href)
            continue

        # Other commercial detail pages in the library
        if "library.tiktok.com" in lower and "other-commercial" in lower:
            urls.add(href)
            continue

    return list(urls)


def scrape_other_commercial(page):
    """
    With filters already set (All countries, date range), just scroll and collect URLs.
    """
    print("\n[OTHER] ==== Scraping Other commercial content (no search term) ====")

    # Let page settle
    page.wait_for_timeout(INITIAL_WAIT_MS)

    # Scroll to load more cards
    for i in range(SCROLL_PASSES):
        page.mouse.wheel(0, 2500)
        page.wait_for_timeout(SCROLL_SLEEP_MS)
        print(f"[OTHER]   scrolled {i+1}/{SCROLL_PASSES}")

    urls = collect_urls_from_page(page)
    print(f"[OTHER] Found {len(urls)} URLs on page.")
    return urls


# ─────────────── MAIN ───────────────

def run():
    print("=== TikTok Other Commercial Content Firehose Scraper ===")

    ads_ws = get_ads_sheet()
    existing = get_existing_urls(ads_ws)
    total_new = 0

    with sync_playwright() as p:
        browser, page = open_other_commercial_page(p)

        urls = scrape_other_commercial(page)
        ts = datetime.utcnow().isoformat()
        new_rows = []

        for u in urls:
            if u not in existing:
                existing.add(u)
                new_rows.append([ts, "other_commercial_bulk", u, "other_commercial"])

        if new_rows:
            print(f"[OTHER] ✏️ Adding {len(new_rows)} new rows...")
            try:
                ads_ws.append_rows(new_rows, value_input_option="RAW")
                total_new += len(new_rows)
            except Exception as e:
                print("[OTHER] ❌ Error writing to 'ads' sheet:", e)
        else:
            print("[OTHER] 0 new URLs to add.")

        browser.close()

    print(f"\n[OTHER] ✅ DONE. Total NEW URLs saved: {total_new}")


if __name__ == "__main__":
    run()

