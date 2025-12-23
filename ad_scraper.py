# ad_scraper.py
#
# TikTok "Other commercial content" scraper (NO API).
#
# FLOW:
#   1) You start this script. It launches its own Chromium window (no CDP).
#   2) It opens: https://library.tiktok.com/other-commercial-content
#   3) You manually:
#        - Set "Ad target country" = "All countries"
#        - Set the date range how you want
#   4) You press ENTER in the terminal.
#   5) For each niche in the "niches" sheet, the script:
#        - Clears the "Advertiser or keyword" / "Search by name or keyword" box
#        - Types the niche
#        - Clicks Search
#        - Scrolls the results
#        - Collects interesting URLs (TikTok video links + detail links)
#        - Appends NEW URLs into the "ads" worksheet in your Google Sheet.
#
# Sheet: 1XNkTaG02oj76pzxt_TC0-o2ug7zTbpSJl3FK5k2jpXQ
# Worksheet "ads" schema:
#   A: timestamp_utc
#   B: search_term
#   C: url           (ad/detail/video URL)
#   D: source        (here: "other_commercial")

from datetime import datetime
import time
from urllib.parse import urljoin, urlparse

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

NICHES_SHEET_NAME = "niches"
ADS_SHEET_NAME = "ads"

OTHER_COMMERCIAL_URL = "https://library.tiktok.com/other-commercial-content"

SCROLL_PASSES = 8
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


def get_niches():
    client = get_sheets_client()
    wb = client.open_by_key(SHEET_ID)
    ws = wb.worksheet(NICHES_SHEET_NAME)
    rows = ws.col_values(1)[1:]  # skip header
    niches = [r.strip() for r in rows if r.strip()]
    print(f"[OTHER] Loaded {len(niches)} niches.")
    return niches


def get_existing_urls(ads_ws):
    urls = ads_ws.col_values(3)[1:]  # column C after header
    existing = set(u.strip() for u in urls if u.strip())
    print(f"[OTHER] Found {len(existing)} existing URLs in sheet.")
    return existing


# ─────────────── BROWSER SETUP ───────────────

def open_other_commercial_page(p):
    """
    Launch a fresh Chromium window and open the Other Commercial Content page.
    We let YOU set the filters, then we don't touch country/date again.
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
    print("  • Set 'Ad target country' to 'All countries'.")
    print("  • Set the date range however you want.")
    print("  • Make sure the page is on the 'Other commercial content' tab.")
    input("[OTHER] When you're done setting filters, press ENTER here to start scraping... ")

    return browser, page


# ─────────────── SEARCH + SCRAPE ───────────────

def collect_urls_from_page(page):
    """
    Given the Other Commercial search results page (after a search),
    collect useful URLs:
      - TikTok video URLs
      - TikTok library detail URLs for other commercial content
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

        # Filter to "interesting" links
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


def search_other_commercial(page, keyword):
    """
    On the Other commercial content page (filters already set),
    change the keyword, run search, scroll, and collect URLs.
    """
    print(f"\n[OTHER] ==== Searching for: {keyword} ====")

    # Make sure we are on the right tab (but don't reload each time)
    if "other-commercial-content" not in (page.url or ""):
        try:
            page.goto(OTHER_COMMERCIAL_URL, wait_until="domcontentloaded", timeout=60000)
        except PlaywrightTimeoutError:
            print("[OTHER] ⚠️ Timeout refreshing Other commercial page; continuing anyway.")

    # Locate the search box – placeholder is something like:
    # "Advertiser name or keyword" / "Search by name or keyword"
    search_box = None
    try:
        search_box = page.wait_for_selector(
            'input[placeholder*="keyword"], '
            'input[placeholder*="Advertiser"], '
            'input[type="search"]',
            timeout=8000,
        )
    except Exception:
        try:
            search_box = page.query_selector("input[type='search']")
        except Exception:
            search_box = None

    if not search_box:
        print("[OTHER] ❌ No search input found; skipping this keyword.")
        return []

    # Clear previous search term and type the new one
    search_box.click()
    search_box.fill("")
    search_box.type(keyword)
    page.wait_for_timeout(300)

    # Click Search button if present
    try:
        btn = page.query_selector("button:has-text('Search')")
        if btn:
            btn.click()
    except Exception:
        pass

    # Also press Enter as backup
    page.keyboard.press("Enter")
    page.wait_for_timeout(INITIAL_WAIT_MS)

    # Scroll to load more cards
    for _ in range(SCROLL_PASSES):
        page.mouse.wheel(0, 2500)
        page.wait_for_timeout(SCROLL_SLEEP_MS)

    urls = collect_urls_from_page(page)
    print(f"[OTHER] Found {len(urls)} URLs for '{keyword}'")
    return urls


# ─────────────── MAIN ───────────────

def run():
    print("=== TikTok Other Commercial Content Scraper ===")
    niches = get_niches()
    if not niches:
        print("[OTHER] No niches found; aborting.")
        return

    ads_ws = get_ads_sheet()
    existing = get_existing_urls(ads_ws)
    total_new = 0

    with sync_playwright() as p:
        browser, page = open_other_commercial_page(p)

        for niche in niches:
            urls = search_other_commercial(page, niche)
            ts = datetime.utcnow().isoformat()
            new_rows = []

            for u in urls:
                if u not in existing:
                    existing.add(u)
                    new_rows.append([ts, niche, u, "other_commercial"])

            if new_rows:
                print(f"[OTHER] ✏️ Adding {len(new_rows)} new rows for '{niche}'")
                try:
                    ads_ws.append_rows(new_rows, value_input_option="RAW")
                    total_new += len(new_rows)
                except Exception as e:
                    print("[OTHER] ❌ Error writing to 'ads' sheet:", e)
            else:
                print(f"[OTHER] 0 new URLs for '{niche}'")

            time.sleep(1)

        browser.close()

    print(f"\n[OTHER] ✅ DONE. Total NEW URLs saved: {total_new}")


if __name__ == "__main__":
    run()

