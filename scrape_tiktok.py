"""
TrendScoutAI – TikTok Shop product scraper (real browser mode)

Main function:

    async def fetch_tiktok_products(urls: List[str]) -> List[Dict]

It returns a list of dicts like:

    {
        "url": url,
        "name": name,
        "price": price_float,
        "sold": sold_float,
        "rating": rating_float,
    }

This version:
- Opens a REAL Chromium window (headless=False)
- Uses a persistent profile ("user-data") so your TikTok login is remembered
"""

from typing import List, Dict
import asyncio
import re
from playwright.async_api import async_playwright


async def scrape_one_product(url: str) -> Dict:
    """
    Scrape a single TikTok Shop product page (PDP).
    """

    async with async_playwright() as p:
        # REAL browser with saved profile
        browser = await p.chromium.launch_persistent_context(
            user_data_dir="user-data",  # folder to store cookies/login
            headless=False              # show the browser window
        )
        page = await browser.new_page()

        await page.goto(url, wait_until="networkidle")

        async def safe_get(selectors: List[str]) -> str:
            """
            Try each CSS selector until one returns non-empty text.
            """
            for sel in selectors:
                try:
                    el = await page.query_selector(sel)
                    if el:
                        txt = await el.text_content()
                        if txt:
                            return txt.strip()
                except Exception:
                    pass
            return ""

        # ---------- PRIMARY SELECTORS ----------

        # Product name
        name = await safe_get([
            'h1[data-e2e="pdp-product-title"]',
            'h1[data-e2e="product-detail-title"]',
            'h1',
            'div[data-e2e="product-title"]',
        ])

        # Raw price / sold / rating text from likely elements
        price_text = await safe_get([
            'div[data-e2e="pdp-price"]',
            'div[data-e2e="product-price"]',
            'div[data-e2e="discount-price"]',
            'span[data-e2e="product-detail-price"]',
        ])

        sold_text = await safe_get([
            'div[data-e2e="sold-info"]',
            'div[data-e2e="sales"]',
            'span:has-text("sold")',
            'span[class*="sold"]',
        ])

        rating_text = await safe_get([
            'div[data-e2e="ratings"]',
            'div[data-e2e="star-rating"]',
            'span[class*="star"]',
        ])

        # Full page text as backup
        page_text = await page.inner_text("body")

        # ---------- HELPERS: text → numbers ----------

        def base_num(raw: str) -> float:
            """
            Turn things like '$32.66', '183.9K', '4.6', '8.5k' into a float.
            Ignore pure percentages like '80%'.
            """
            if not raw:
                return 0.0

            s = raw.replace(",", "").lower().strip()

            # Ignore percentages (like '80%' or 'save 80%')
            if "%" in s:
                return 0.0

            # K / M suffix
            if "k" in s:
                try:
                    return float(s.replace("k", "")) * 1_000
                except ValueError:
                    return 0.0
            if "m" in s:
                try:
                    return float(s.replace("m", "")) * 1_000_000
                except ValueError:
                    return 0.0

            # Strip everything except digits and dot
            num = "".join(ch for ch in s if (ch.isdigit() or ch == "."))
            if not num:
                return 0.0

            try:
                return float(num)
            except ValueError:
                return 0.0

        def extract_price(p_text: str, full_text: str) -> float:
            """
            Find the most likely product price from all $xx.xx values.

            Strategy:
            - Collect ALL $xx.xx patterns from price_text + page_text
            - Convert to numbers
            - Prefer the smallest price that is at least $5.00
              (to skip tiny things like $1.87 shipping or coupons)
            - If nothing >= 5, fall back to the smallest value.
            """
            all_matches: List[str] = []

            for src in (p_text, full_text):
                if not src:
                    continue
                matches = re.findall(r"\$\s*\d[\d,]*(?:\.\d{1,2})?", src)
                all_matches.extend(matches)

            values: List[float] = []
            for mtxt in all_matches:
                val = base_num(mtxt)
                if val > 0:
                    values.append(val)

            if not values:
                return 0.0

            values.sort()

            # Try to pick a "real" price >= $5
            for v in values:
                if v >= 5.0:
                    return v

            # Otherwise, just return the smallest value
            return values[0]

        def extract_sold(s_text: str, full_text: str) -> float:
            """Find something like '183.9K sold' and convert to a number."""
            for src in (s_text, full_text):
                if not src:
                    continue
                m = re.search(r"(\d[\d.,]*\s*[kKmM]?)\s+sold", src)
                if m:
                    return base_num(m.group(1))
            return 0.0

        def extract_rating(r_text: str, full_text: str) -> float:
            """
            Find rating values between 0 and 5 (like 4.6).
            We may see multiple numbers:
                1.9 (from '1.9K reviews')
                4.6 (actual rating)
            We collect them and return the HIGHEST in 0–5.
            """
            vals: List[float] = []

            for src in (r_text, full_text):
                if not src:
                    continue
                matches = re.findall(r"(\d\.\d)", src)
                for mtxt in matches:
                    try:
                        v = float(mtxt)
                        if 0.0 < v <= 5.0:
                            vals.append(v)
                    except ValueError:
                        pass

            if not vals:
                return 0.0

            return max(vals)

        price_val = extract_price(price_text, page_text)
        sold_val = extract_sold(sold_text, page_text)
        rating_val = extract_rating(rating_text, page_text)

        await browser.close()

    return {
        "url": url,
        "name": name,
        "price": price_val,
        "sold": sold_val,
        "rating": rating_val,
    }


async def fetch_tiktok_products(urls: List[str]) -> List[Dict]:
    """
    Scrape multiple TikTok product URLs concurrently.
    """
    clean_urls = [u for u in urls if u]
    tasks = [scrape_one_product(u) for u in clean_urls]
    return await asyncio.gather(*tasks)


if __name__ == "__main__":
    # Optional local testing (not used by FastAPI)
    test_urls = [
        # "https://www.tiktok.com/shop/pdp/..."
    ]

    async def _test():
        results = await fetch_tiktok_products(test_urls)
        for r in results:
            print(r)

    asyncio.run(_test())

