import math
from collections import defaultdict, Counter

import gspread
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SERVICE_ACCOUNT_FILE = "service_account.json"
SHEET_ID = "1XNkTaG02oj76pzxt_TC0-o2ug7zTbpSJl3FK5k2jpXQ"

VIDEOS_SHEET = "videos"
NICHE_STATS_SHEET = "niche_stats"
HASHTAG_HISTORY_SHEET = "hashtag_history"


def parse_int(x):
    try:
        s = str(x).strip()
        if s == "":
            return 0
        return int(float(s))
    except:
        return 0


def connect():
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)
    return client.open_by_key(SHEET_ID)


def header_map(header_row):
    return {str(h).strip().lower(): i for i, h in enumerate(header_row) if str(h).strip()}


def get_val(row, cmap, name, default=""):
    idx = cmap.get(name)
    if idx is None or idx >= len(row):
        return default
    return row[idx]


def main():
    sh = connect()
    videos_ws = sh.worksheet(VIDEOS_SHEET)
    niche_ws = sh.worksheet(NICHE_STATS_SHEET)
    hh_ws = sh.worksheet(HASHTAG_HISTORY_SHEET)

    videos = videos_ws.get_all_values()
    niche_stats = niche_ws.get_all_values()
    hashtag_history = hh_ws.get_all_values()

    print(f"[INFO] videos rows (incl header): {len(videos)}")
    print(f"[INFO] niche_stats rows (incl header): {len(niche_stats)}")
    print(f"[INFO] hashtag_history rows (incl header): {len(hashtag_history)}")

    # Basic sheet presence checks
    if len(niche_stats) < 2:
        print("[FAIL] niche_stats has no data rows (only header or empty).")
        return

    # Videos header mapping
    v_header = videos[0]
    vmap = header_map(v_header)

    # Try common column names (adjust if yours differ)
    niche_key = "niche"
    likes_key = "likes"
    comments_key = "comments"
    favorites_key = "favorites"
    shares_key = "shares"
    hashtags_key = "hashtags"

    missing = [k for k in [niche_key, likes_key, comments_key, favorites_key, shares_key] if k not in vmap]
    if missing:
        print(f"[WARN] videos is missing expected columns: {missing}")
        print("       This often causes wrong stats. Check videos header row.")
        print("       Header:", v_header)

    # Build true aggregates from videos
    by_niche = defaultdict(list)
    hashtag_counter_global = Counter()

    for r in videos[1:]:
        niche = str(get_val(r, vmap, niche_key, "")).strip()
        if not niche:
            continue
        likes = parse_int(get_val(r, vmap, likes_key, 0))
        comments = parse_int(get_val(r, vmap, comments_key, 0))
        favorites = parse_int(get_val(r, vmap, favorites_key, 0))
        shares = parse_int(get_val(r, vmap, shares_key, 0))
        engagement = likes + comments + favorites + shares

        tags = str(get_val(r, vmap, hashtags_key, "")).strip()
        if tags:
            for h in tags.split(","):
                h = h.strip()
                if h:
                    hashtag_counter_global[h] += 1

        by_niche[niche].append((likes, comments, favorites, shares, engagement))

    distinct_niches = len(by_niche)
    print(f"[INFO] distinct niches in videos: {distinct_niches}")

    # Parse niche_stats header
    ns_header = niche_stats[0]
    nsmap = header_map(ns_header)

    # Expect these (adjust if your analyzer uses different names)
    ns_required = ["niche", "video_count", "avg_likes", "avg_comments", "avg_favorites", "avg_shares", "avg_engagement_metric"]
    missing_ns = [k for k in ns_required if k not in nsmap]
    if missing_ns:
        print(f"[WARN] niche_stats missing expected columns: {missing_ns}")
        print("       Header:", ns_header)

    # Validate top rows + detect impossible values
    bad_rows = 0
    huge_outliers = 0

    # Build a quick lookup from niche_stats
    stats_lookup = {}
    for row in niche_stats[1:]:
        niche = str(get_val(row, nsmap, "niche", "")).strip()
        if not niche:
            continue
        stats_lookup[niche] = row

    # Compare 10 biggest niches by video_count (from niche_stats)
    def ns_int(row, key): return parse_int(get_val(row, nsmap, key, 0))
    def ns_float(row, key):
        try:
            return float(str(get_val(row, nsmap, key, 0)).strip() or 0.0)
        except:
            return 0.0

    # Sort by niche_stats video_count
    rows_sorted = sorted(niche_stats[1:], key=lambda r: ns_int(r, "video_count"), reverse=True)[:10]

    print("\n[CHECK] Top 10 niches compare niche_stats vs recomputed from videos:")
    for row in rows_sorted:
        niche = str(get_val(row, nsmap, "niche", "")).strip()
        vc = ns_int(row, "video_count")
        avg_eng = ns_float(row, "avg_engagement_metric")

        vid_data = by_niche.get(niche, [])
        if not vid_data:
            print(f" - {niche}: [FAIL] in niche_stats but not found in videos")
            bad_rows += 1
            continue

        true_vc = len(vid_data)
        true_avg_eng = sum(x[4] for x in vid_data) / max(1, true_vc)

        # Ratio check
        ratio = (avg_eng / true_avg_eng) if true_avg_eng else (math.inf if avg_eng else 1.0)

        flag = ""
        if vc != true_vc:
            flag += f" vc_mismatch({vc} vs {true_vc})"
        if true_avg_eng and (ratio < 0.7 or ratio > 1.3):
            flag += f" avg_eng_off(ratio={ratio:.2f})"
            huge_outliers += 1

        # Impossible value checks
        if avg_eng < 0 or vc < 0:
            flag += " impossible_values"
            bad_rows += 1

        print(f" - {niche}: vc={vc} (true {true_vc}), avg_eng={avg_eng:.2f} (true {true_avg_eng:.2f}){('  <-- '+flag) if flag else ''}")

    # Global hashtag sanity
    top_global = hashtag_counter_global.most_common(10)
    print("\n[CHECK] Top 10 hashtags in videos (global):")
    for h, c in top_global:
        print(f" - {h}: {c}")

    # Basic hashtag_history check
    if len(hashtag_history) < 2:
        print("\n[WARN] hashtag_history has no data rows.")
    else:
        hh_header = hashtag_history[0]
        print("\n[INFO] hashtag_history header:", hh_header)
        print("[INFO] hashtag_history first data row:", hashtag_history[1])

    print("\n[SUMMARY]")
    if bad_rows == 0 and huge_outliers == 0:
        print("✅ Looks consistent: niche_stats aligns with videos aggregation for the biggest niches.")
    else:
        print(f"⚠️ Issues found: bad_rows={bad_rows}, outlier_niches={huge_outliers}")
        print("   If you see vc mismatch or avg_eng ratio way off, your analyzer is likely using wrong columns/indexes or filtering incorrectly.")


if __name__ == "__main__":
    main()

