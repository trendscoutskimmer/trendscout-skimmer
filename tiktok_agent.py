from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from datetime import datetime
from urllib.parse import urlparse, quote_plus
import time

import gspread
from google.oauth2.service_account import Credentials

# ───────────────────────── CONFIG ─────────────────────────

DEBUG_URL = "http://127.0.0.1:9222"   # Chrome remote debugging (must be running)
MAX_VIDEOS_PER_NICHE = 5              # bump later when stable
SCROLL_PASSES = 8                     # how many scroll cycles on the search results

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SERVICE_ACCOUNT_FILE = "service_account.json"

SHEET_ID = "1XNkTaG02oj76pzxt_TC0-o2ug7zTbpSJl3FK5k2jpXQ"
NICHES_SHEET_NAME = "niches"
VIDEOS_SHEET_NAME = "videos"

# skip my own account
MY_HANDLES = {"@deepdarklost"}


# ─────────────── SHEETS HELPERS ───────────────

def get_sheets():
    """Authorize service account and return (niches_ws, videos_ws)."""
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)
    sh = client.open_by_key(SHEET_ID)
    niches_ws = sh.worksheet(NICHES_SHEET_NAME)
    videos_ws = sh.worksheet(VIDEOS_SHEET_NAME)
    return niches_ws, videos_ws


def load_niches(niches_ws):
    """Read column A from 'niches' (skip header & blanks)."""
    values = niches_ws.col_values(1)
    niches = []
    for v in values[1:]:  # skip header row
        v = (v or "").strip()
        if v:
            niches.append(v)
    print(f"[INFO] Loaded {len(niches)} niches from sheet.")
    return niches


def get_existing_video_ids(videos_ws, limit=20000):
    """
    Build a set of existing video_ids so we don't append duplicates.
    Assumes column B is 'video_id' based on your header.
    """
    try:
        col_vals = videos_ws.col_values(2)  # 1-indexed; col 2 = video_id
        # skip header
        existing = set(v.strip() for v in col_vals[1:] if v and v.strip())
        print(f"[INFO] Loaded {len(existing)} existing video_ids (for dedupe).")
        return existing
    except Exception as e:
        print("[WARN] Could not load existing video_ids for dedupe:", repr(e))
        return set()


# ─────────────── SMALL PARSERS ───────────────

def parse_video_id(url: str) -> str:
    """Extract numeric video ID from TikTok URL."""
    try:
        parts = [p for p in urlparse(url).path.split("/") if p]
        if "video" in parts:
            idx = parts.index("video")
            if idx + 1 < len(parts):
                return parts[idx + 1]
    except Exception:
        pass
    return ""


def parse_creator_from_url(url: str) -> str:
    """Extract @handle from URL like /@user/video/123."""
    try:
        parts = urlparse(url).path.split("/")
        for p in parts:
            if p.startswith("@"):
                return p
    except Exception:
        pass
    return ""


def parse_count(text: str) -> int:
    """Turn '1.2M' / '345.6K' / '1234' into an int."""
    if not text:
        return 0
    t = text.strip().lower().replace(",", "")
    try:
        if t.endswith("m"):
            return int(float(t[:-1]) * 1_000_000)
        if t.endswith("k"):
            return int(float(t[:-1]) * 1_000)
        return int(float(t))
    except Exception:
        return 0


# ─────────────── VIDEO METADATA ───────────────

def extract_video_metadata(page, url: str):
    """
    From an open TikTok video page, grab:
      creator, title, description, hashtags,
      likes, comments, favorites, shares,
      engagement_metric.
    """
    creator = parse_creator_from_url(url)
    title = ""
    description = ""
    hashtags = []

    # Description / title
    desc_el = (
        page.query_selector('h1[data-e2e="browse-video-desc"]')
        or page.query_selector('strong[data-e2e="browse-video-desc"]')
        or page.query_selector('[data-e2e="video-desc"]')
    )
    if desc_el:
        description = (desc_el.inner_text() or "").strip()
        title = description
    else:
        title = (page.title() or "").strip()
        description = title

    # Hashtags
    for a in page.query_selector_all('a[href*="/tag/"]'):
        txt = (a.inner_text() or "").strip()
        if txt.startswith("#"):
            hashtags.append(txt)
    hashtags_str = ",".join(sorted(set(hashtags))) if hashtags else ""

    # Stats
    likes = 0
    comments = 0
    favorites = 0
    shares = 0

    likes_el = page.query_selector('[data-e2e="like-count"]')
    if likes_el:
        likes = parse_count(likes_el.inner_text())

    comments_el = page.query_selector('[data-e2e="comment-count"]')
    if comments_el:
        comments = parse_count(comments_el.inner_text())

    # Favorites (bookmark)
    fav_selectors = [
        '[data-e2e="favorite-count"]',
        '[data-e2e="collect-count"]',
        '[data-e2e="bookmark-count"]',
    ]
    for sel in fav_selectors:
        el = page.query_selector(sel)
        if not el:
            continue
        v = parse_count((el.inner_text() or "").strip())
        if v > 0:
            favorites = v
            break

    # Favorites fallback: any counter that isn't like/comment/share
    if favorites == 0:
        try:
            counters = page.eval_on_selector_all(
                "*[data-e2e*='count']",
                "els => els.map(e => [e.getAttribute('data-e2e'), e.innerText])",
            )
            for attr, txt in counters:
                if not attr:
                    continue
                al = attr.lower()
                if "like-count" in al or "comment-count" in al or "share-count" in al:
                    continue
                v = parse_count((txt or "").strip())
                if v > 0:
                    favorites = v
                    break
        except Exception:
            pass

    # Shares
    share_el = page.query_selector('[data-e2e="share-count"]')
    if share_el:
        shares = parse_count((share_el.inner_text() or "").strip())

    # Shares fallback: only counters that contain 'share'
    if shares == 0:
        try:
            counters = page.eval_on_selector_all(
                "*[data-e2e*='count']",
                "els => els.map(e => [e.getAttribute('data-e2e'), e.innerText])",
            )
            for attr, txt in counters:
                if not attr:
                    continue
                if "share" not in attr.lower():
                    continue
                v = parse_count((txt or "").strip())
                if v > 0:
                    shares = v
                    break
        except Exception:
            pass

    engagement_metric = float(likes + comments + favorites + shares)

    return (
        creator,
        title,
        description,
        hashtags_str,
        likes,
        comments,
        favorites,
        shares,
        engagement_metric,
    )


# ─────────────── NICHE SEARCH ───────────────

def force_videos_tab(page):
    """
    TikTok 'Top' tab is unreliable. Always switch to 'Videos' tab.
    This function is safe to call repeatedly.
    """
    # If Top says "No results found", it often still works on Videos
    try:
        if page.get_by_text("No results found").count() > 0:
            print("[WARN] 'Top' shows no results — forcing Videos tab…")
    except Exception:
        pass

    # Try ARIA role tab first
    try:
        page.get_by_role("tab", name="Videos").click(timeout=5000)
        page.wait_for_timeout(1200)
        return True
    except Exception:
        pass

    # Fallback: click by visible text
    try:
        page.get_by_text("Videos", exact=True).click(timeout=5000)
        page.wait_for_timeout(1200)
        return True
    except Exception:
        return False


def scrape_niche_search(page, niche: str, max_videos: int):
    """
    For a given niche:
      - open search page
      - switch to Videos tab
      - scroll
      - collect up to max_videos unique video URLs,
        skipping my own handle and the first few personalized tiles.
    """
    q = quote_plus(niche.strip())
    search_url = f"https://www.tiktok.com/search?q={q}"

    print(f"\n=== Searching niche: {niche} ===")
    print("[INFO] URL:", search_url)

    try:
        page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
    except PlaywrightTimeoutError:
        print("[WARN] Timeout on search page, continuing...")

    # Always switch to Videos tab
    ok = force_videos_tab(page)
    if ok:
        print("[OK] Switched to Videos tab.")
    else:
        print("[WARN] Could not click Videos tab (continuing anyway).")

    # Wait for video tiles (best effort)
    try:
        page.wait_for_selector('a[href*="/video/"]', timeout=15000)
        print("[OK] Found video tiles.")
    except PlaywrightTimeoutError:
        print("[WARN] No video tiles detected yet, scrolling anyway.")

    # Scroll to load more videos
    for _ in range(SCROLL_PASSES):
        page.mouse.wheel(0, 1600)
        page.wait_for_timeout(1800)

    # Collect links
    elements = page.query_selector_all('a[href*="/video/"]')

    # Skip first 3 (often personalized)
    if len(elements) > 3:
        elements = elements[3:]

    links = []
    seen = set()

    for a in elements:
        href = a.get_attribute("href")
        if not href:
            continue

        if href.startswith("/"):
            href = "https://www.tiktok.com" + href

        # Remove query params
        href = href.split("?", 1)[0]

        if "/video/" not in href:
            continue

        creator = parse_creator_from_url(href)
        if creator and creator in MY_HANDLES:
            continue

        if href not in seen:
            seen.add(href)
            links.append(href)

        if len(links) >= max_videos:
            break

    print(f"[INFO] Collected {len(links)} URLs for '{niche}'.")
    return links


# ─────────────── MAIN ───────────────

def run():
    print("[INFO] Authorizing Google Sheets...")
    niches_ws, videos_ws = get_sheets()
    niches = load_niches(niches_ws)
    if not niches:
        print("[WARN] No niches found. Aborting.")
        return

    existing_video_ids = get_existing_video_ids(videos_ws)

    with sync_playwright() as p:
        print("[INFO] Connecting to Chrome over CDP:", DEBUG_URL)
        browser = p.chromium.connect_over_cdp(DEBUG_URL)

        # Use existing context if Chrome already has one
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.new_page()

        total_written = 0
        now_iso = datetime.utcnow().isoformat()

        for niche in niches:
            urls = scrape_niche_search(page, niche, MAX_VIDEOS_PER_NICHE)

            for url in urls:
                video_id = parse_video_id(url)
                if not video_id:
                    print("   [WARN] Could not parse video_id, skipping:", url)
                    continue

                if video_id in existing_video_ids:
                    print("   [SKIP] Already have video_id:", video_id)
                    continue

                print(f" → Visiting video: {url}")
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=60000)
                except PlaywrightTimeoutError:
                    print("   [WARN] Timeout on video page, skipping.")
                    continue

                time.sleep(2)

                (
                    creator,
                    title,
                    description,
                    hashtags_str,
                    likes,
                    comments,
                    favorites,
                    shares,
                    engagement_metric,
                ) = extract_video_metadata(page, url)

                if creator in MY_HANDLES:
                    print("   [SKIP] My own video:", creator)
                    continue

                # Your videos sheet schema (as you pasted):
                # niche, video_id, url, creator, title, description, hashtags,
                # likes, comments, favorites, shares, engagement_metric, status, ...
                row = [
                    niche,              # 0
                    video_id,           # 1
                    url,                # 2
                    creator,            # 3
                    title,              # 4
                    description,        # 5
                    hashtags_str,       # 6
                    likes,              # 7
                    comments,           # 8
                    favorites,          # 9
                    shares,             # 10
                    engagement_metric,  # 11
                    "NEW",              # 12 status for score_agent
                    "",                 # 13 viral_score (blank)
                    "",                 # 14 engagement_score (blank)
                    "",                 # 15 hashtag_score (blank)
                    "",                 # 16 niche_heat_score (blank)
                    "",                 # 17 suggestions (blank)
                    "",                 # 18 last_scored_at (blank)
                    "",                 # 19 creator_username (blank)
                    "",                 # 20 creator_profile_url (blank)
                    "",                 # 21 creator_enriched (blank)
                ]

                try:
                    print(f"   [WRITE] Appending row (video_id={video_id}) niche='{niche}'")
                    videos_ws.append_row(row, value_input_option="RAW")
                    total_written += 1
                    existing_video_ids.add(video_id)
                except Exception as e:
                    print("   [ERR] Error writing row to Google Sheets:", repr(e))

                # small delay to be polite to Sheets + TikTok
                time.sleep(0.5)

        print(f"\n✅ Done. Total rows written to 'videos': {total_written}")
        browser.close()


if __name__ == "__main__":
    run()

