import os
import json
from collections import defaultdict

import gspread
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json")
SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "").strip()

VIDEOS_SHEET_NAME = os.getenv("VIDEOS_SHEET_NAME", "videos")
CREATORS_SHEET_NAME = os.getenv("CREATORS_SHEET_NAME", "creators")


def get_sheet():
    if not SHEET_ID:
        raise RuntimeError("Missing GOOGLE_SHEET_ID env.")
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)
    return client.open_by_key(SHEET_ID)


def safe_float(v):
    try:
        return float(str(v).replace(",", "").strip())
    except Exception:
        return 0.0


def normalize_header(header):
    return {(h or "").strip().lower(): i for i, h in enumerate(header)}


def main(min_viral_score: float = 60.0):
    sh = get_sheet()
    vws = sh.worksheet(VIDEOS_SHEET_NAME)

    rows = vws.get_all_values()
    if len(rows) < 2:
        print("No videos.")
        return

    header = rows[0]
    hmap = normalize_header(header)

    def g(row, key, default=""):
        idx = hmap.get(key)
        if idx is None or idx >= len(row):
            return default
        return row[idx]

    creators = defaultdict(lambda: {"videos": 0, "avg_viral": 0.0, "top_niches": defaultdict(int)})

    for r in rows[1:]:
        creator = (g(r, "creator", "") or g(r, "author", "")).strip()
        if not creator:
            continue

        viral = safe_float(g(r, "viral_score", 0))
        if viral < min_viral_score:
            continue

        niche = (g(r, "niche", "") or "").strip()
        creators[creator]["videos"] += 1
        creators[creator]["avg_viral"] += viral
        if niche:
            creators[creator]["top_niches"][niche] += 1

    out = []
    for creator, d in creators.items():
        cnt = d["videos"]
        avg = d["avg_viral"] / cnt if cnt else 0.0
        top_niches = sorted(d["top_niches"].items(), key=lambda x: x[1], reverse=True)
        top_niches = [n for n, _ in top_niches[:3]]
        out.append([creator, str(cnt), str(round(avg, 2)), json.dumps(top_niches)])

    out.sort(key=lambda r: float(r[2]), reverse=True)

    cws = sh.worksheet(CREATORS_SHEET_NAME)
    cws.clear()
    cws.update([["creator", "videos_scored", "avg_viral_score", "top_niches"]] + out)

    print(f"Updated creators sheet: {len(out)} creators.")


if __name__ == "__main__":
    main()

