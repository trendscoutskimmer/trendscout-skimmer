import os
import time
import json
import requests
import gspread
from dotenv import load_dotenv

load_dotenv(dotenv_path=".env", override=True)

SHEET_ID = (os.getenv("GOOGLE_SHEET_ID") or "").strip()
if not SHEET_ID:
    raise RuntimeError("Missing GOOGLE_SHEET_ID in .env")

SERVICE_ACCOUNT = "service_account.json"
if not os.path.exists(SERVICE_ACCOUNT):
    SERVICE_ACCOUNT = "service-account.json"
if not os.path.exists(SERVICE_ACCOUNT):
    raise RuntimeError("Missing service_account.json (or service-account.json) in project root")

def a1(col: int, row: int) -> str:
    """1-based col/row -> A1"""
    s = ""
    while col:
        col, r = divmod(col - 1, 26)
        s = chr(65 + r) + s
    return f"{s}{row}"

def fetch_thumbnail_from_oembed(video_url: str, timeout=15) -> str:
    # TikTok oEmbed returns JSON containing thumbnail_url
    endpoint = "https://www.tiktok.com/oembed"
    r = requests.get(endpoint, params={"url": video_url}, timeout=timeout, headers={
        "User-Agent": "Mozilla/5.0"
    })
    r.raise_for_status()
    data = r.json()
    thumb = (data.get("thumbnail_url") or "").strip()
    return thumb

def main():
    gc = gspread.service_account(filename=SERVICE_ACCOUNT)
    sh = gc.open_by_key(SHEET_ID)
    ws = sh.worksheet("blog_posts")

    values = ws.get_all_values()
    if not values or len(values) < 2:
        print("No rows found in blog_posts.")
        return

    header = [h.strip() for h in values[0]]

    def idx(name: str):
        try:
            return header.index(name)
        except ValueError:
            return None

    i_video = idx("source_video_url")
    i_img = idx("blog_image_url")
    i_src = idx("blog_image_source")

    if i_video is None:
        raise RuntimeError("blog_posts missing required column: source_video_url")
    if i_img is None:
        raise RuntimeError("blog_posts missing required column: blog_image_url")
    if i_src is None:
        print("[WARN] blog_image_source column not found; will only fill blog_image_url.")

    updates = []
    total = 0
    filled = 0
    failed = 0

    # Start from row 2 (row 1 is header)
    for r in range(2, len(values) + 1):
        row = values[r - 1]
        video_url = (row[i_video] if i_video < len(row) else "").strip()
        cur_img = (row[i_img] if i_img < len(row) else "").strip()

        if not video_url:
            continue
        if cur_img:
            continue

        total += 1
        try:
            thumb = fetch_thumbnail_from_oembed(video_url)
            if thumb:
                # blog_image_url cell
                updates.append({
                    "range": a1(i_img + 1, r),
                    "values": [[thumb]],
                })
                # blog_image_source cell
                if i_src is not None:
                    updates.append({
                        "range": a1(i_src + 1, r),
                        "values": [["tiktok_oembed_thumbnail"]],
                    })
                filled += 1
                print(f"[OK] Row {r}: set blog_image_url")
            else:
                failed += 1
                print(f"[FAIL] Row {r}: no thumbnail_url returned")
        except Exception as e:
            failed += 1
            print(f"[ERR] Row {r}: {e}")

        # be polite to TikTok
        time.sleep(0.25)

        # Flush in chunks to reduce API calls
        if len(updates) >= 80:
            ws.batch_update(updates, value_input_option="RAW")
            updates = []

    if updates:
        ws.batch_update(updates, value_input_option="RAW")

    print("\n--- DONE ---")
    print("Candidates processed:", total)
    print("Filled:", filled)
    print("Failed:", failed)

if __name__ == "__main__":
    main()

