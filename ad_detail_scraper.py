# ad_detail_scraper.py
#
# Second-pass scraper for TikTok Ad Library.
# Reads the "ads" sheet, visits each ad_url, and tries to find a product /
# landing link on the ad detail page. Saves it into a new column:
#
#   product_link
#
# Sheet: 1XNkTaG02oj76pzxt_TC0-o2ug7zTbpSJl3FK5k2jpXQ
# Worksheet "ads" schema (after this script runs):
#   A: timestamp_utc
#   B: search_term
#   C: ad_url
#   D: source
#   E: product_link

from datetime import datetime
from urllib.parse import urlparse
import time

import gspread
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# ───────────────────────── CONFIG ─────────────────────────

SERVICE_ACCOUNT_FILE = "service_account.json"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SHEET_ID = "1XNkTaG02oj76pzxt_TC0-o2ug7zTbpSJl3FK5k2jpXQ"

ADS_SHEET_NAME = "ads"

# How long to wait for each ad detail page to load
PAGE_TIMEOUT_MS = 30000
IDLE_WAIT_MS = 3000


# ─────────────── GOOGLE SHEETS HELPERS ───────────────

def get_sheets_client():
    creds = Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=SCOPES,
    )
    return gspread.authorize(creds)


def get_ads_sheet():
    client = get_sheets_client()
    wb = client.open_by_key(SHEET_ID)
    ws = wb.worksheet(ADS_SHEET_NAME)
    return ws


def ensure_product_link_header(ws):
    """
    Make sure column E has a header 'product_link'.
    If it's missing, set it.
    """
    header_row = ws.row_values(1)
    # We expect at least 4 columns already; we add the 5th as product_link.
    if len(header_row) < 5 or header_row[4].strip().lower() != "product_link":
        # Set header in column 5
        ws.update_cell(1, 5, "product_link")
        print("[DETAIL] Set header for column E: product_link")
    else:
        print("[DETAIL] 'product_link' header already exists.")


def get_rows_to_process(ws):
    """
    Return a list of (row_index, ad_url) where product_link is empty.
    Row indices are 2-based (since row 1 is the header).
    """
    all_values = ws.get_all_values()
    rows = []
    for idx, row in enumerate(all_values[1:], start=2):  # start=2 for sheet row index
        # row: [timestamp, search_term, ad_url, source, product_link?]
        if len(row) < 3:
            continue
        ad_url = row[2].strip()
        if not ad_url:
            continue

        product_link = ""
        if len(row) >= 5:
            product_link = row[4].strip()

        # Only process rows with empty product_link
        if not product_link:
            rows.append((idx, ad_url))

    print(f"[DETAIL] Found {len(rows)} ads needing product_link.")
    return rows


# ─────────────── PRODUCT LINK HEURISTICS ───────────────

def is_external_url(href: str) -> bool:
    """
    True if href is an external (non-TikTok) URL.
    """
    try:
        parsed = urlparse(href)
        host = (parsed.netloc or "").lower()
    except Exception:
        return False

    if not host:
        return False

    # Treat anything not containing tiktok.com as external
    return "tiktok.com" not in host


def looks_like_shop_or_product(href: str) -> bool:
    """
    True if href looks like a product or shop link, even if it's still on TikTok.
    """
    h = href.lower()
    keywords = ["product", "products", "shop", "item", "detail", "offer", "buy"]
    return any(k in h for k in keywords)


def extract_candidate_product_link(page):
    """
    Scan all <a> tags on the ad detail page and return the "best" candidate link.
    Priority:
      1) External (non-TikTok) URLs
      2) TikTok URLs that look like product/shop/item pages
      3) Fallback: None
    """
    anchors = page.query_selector_all("a")
    external_candidates = []
    tiktok_product_candidates = []

    for a in anchors:
        href = a.get_attribute("href")
        if not href:
            continue
        href = href.strip()
        if not href or href.startswith("#"):
            continue

        # Normalize protocols
        if href.startswith("//"):
            href = "https:" + href

        # External link?
        if href.startswith("http") and is_external_url(href):
            external_candidates.append(href)
            continue

        # TikTok product/shop-ish?
        if "tiktok.com" in href.lower() and looks_like_shop_or_product(href):
            tiktok_product_candidates.append(href)

    if external_candidates:
        # First external is usually the landing page (shopify, amazon, etc.)
        return external_candidates[0]

    if tiktok_product_candidates:
        # If no external, maybe it's a TikTok Shop link
        return tiktok_product_candidates[0]

    return ""


# ─────────────── MAIN SCRAPER LOGIC ───────────────

def process_ad_page(page, ad_url: str) -> str:
    """
    Open a single ad_url and try to extract a product_link.
    Returns the product_link (or empty string if none).
    """
    print(f"[DETAIL] Visiting ad: {ad_url}")
    try:
        page.goto(ad_url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
    except TimeoutError:
        print("[DETAIL] ⚠️ Timeout loading ad page, continuing anyway.")

    page.wait_for_timeout(IDLE_WAIT_MS)

    product_link = extract_candidate_product_link(page)
    if product_link:
        print(f"[DETAIL] ↳ Found product link: {product_link}")
    else:
        print("[DETAIL] ↳ No product link found on this ad.")
    return product_link


def run():
    print("=== TikTok Ad Detail Scraper (product links) ===")
    ws = get_ads_sheet()
    ensure_product_link_header(ws)
    rows = get_rows_to_process(ws)

    if not rows:
        print("[DETAIL] No rows require processing. Exiting.")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=80)
        context = browser.new_context()
        page = context.new_page()

        for row_index, ad_url in rows:
            product_link = process_ad_page(page, ad_url)

            if product_link:
                try:
                    ws.update_cell(row_index, 5, product_link)
                except Exception as e:
                    print(f"[DETAIL] ❌ Error updating sheet at row {row_index}: {e!r}")
            else:
                # Optionally mark as "none" so we don't retry forever
                # ws.update_cell(row_index, 5, "none")
                pass

            # Be polite; small pause between ads
            time.sleep(1)

        browser.close()

    print("\n[DETAIL] ✅ Done processing ad details.")


if __name__ == "__main__":
    run()

