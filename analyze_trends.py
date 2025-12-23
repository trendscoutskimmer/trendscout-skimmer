import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple, Optional

import gspread


# =========================
# CONFIG
# =========================
SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json")
SHEET_ID = os.getenv("GOOGLE_SHEET_ID") or os.getenv("SHEET_ID")

VIDEOS_SHEET = os.getenv("VIDEOS_SHEET", "videos")
NICHE_STATS_SHEET = os.getenv("NICHE_STATS_SHEET", "niche_stats")
HASHTAG_HISTORY_SHEET = os.getenv("HASHTAG_HISTORY_SHEET", "hashtag_history")

RECENT_DAYS = int(os.getenv("RECENT_DAYS", "7"))


# =========================
# HELPERS
# =========================
def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_dt(s: str) -> Optional[datetime]:
    """
    Returns timezone-aware UTC datetime or None.
    Handles:
      - 2025-12-14T13:27:23.660883+00:00
      - 2025-12-14T13:27:23Z
      - 2025-12-14 13:27:23  (naive -> assume UTC)
    """
    s = (s or "").strip()
    if not s:
        return None

    s = s.replace("Z", "+00:00")

    # Try ISO first
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            # naive -> assume UTC
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt
    except Exception:
        pass

    # Try common non-ISO formats (Sheets sometimes)
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
        "%m/%d/%Y %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(s, fmt)
            dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            continue

    return None


def safe_float(x: Any, default: float = 0.0) -> float:
    try:
        if x is None:
            return default
        s = str(x).strip()
        if not s:
            return default
        s = s.replace(",", "")
        return float(s)
    except Exception:
        return default


def clean_text(x: Any) -> str:
    if x is None:
        return ""
    return str(x).strip().replace("\u00a0", " ")


def header_map(header_row: List[str]) -> Dict[str, int]:
    m = {}
    for i, h in enumerate(header_row):
        key = clean_text(h).lower()
        if key:
            m[key] = i
    return m


def pick(row: List[str], hm: Dict[str, int], key: str, default: str = "") -> str:
    idx = hm.get(key)
    if idx is None:
        return default
    return row[idx] if idx < len(row) else default


def get_sheet():
    if not SHEET_ID:
        raise RuntimeError("Missing GOOGLE_SHEET_ID env var.")
    gc = gspread.service_account(filename=SERVICE_ACCOUNT_FILE)
    return gc.open_by_key(SHEET_ID)


def get_ws(sh, title: str):
    try:
        return sh.worksheet(title)
    except Exception:
        return sh.add_worksheet(title=title, rows=2000, cols=20)


def ws_all(ws) -> Tuple[List[str], List[List[str]]]:
    rows = ws.get_all_values()
    if not rows:
        return [], []
    return rows[0], rows[1:]


def write_sheet(ws, header: List[str], rows: List[List[Any]]):
    ws.clear()
    ws.update(range_name="A1", values=[header], value_input_option="RAW")
    if rows:
        ws.update(range_name="A2", values=rows, value_input_option="RAW")


HASHTAG_RE = re.compile(r"#\w+", re.UNICODE)

def extract_hashtags(raw: str) -> List[str]:
    """
    Extract hashtags and drop junk like '#1300000' (no letters).
    """
    t = clean_text(raw)
    if not t:
        return []
    found = HASHTAG_RE.findall(t)
    out = []
    for h in found:
        h = h.strip().rstrip(",").lower()
        # drop purely numeric hashtags
        if re.search(r"[a-zA-Z]", h) is None:
            continue
        out.append(h)
    return out


def mean(xs: List[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


# =========================
# ANALYZE
# =========================
def main():
    sh = get_sheet()
    videos_ws = get_ws(sh, VIDEOS_SHEET)
    niche_ws = get_ws(sh, NICHE_STATS_SHEET)
    hashtag_ws = get_ws(sh, HASHTAG_HISTORY_SHEET)

    v_header, v_rows = ws_all(videos_ws)
    if not v_header or not v_rows:
        print("[WARN] videos sheet empty. Nothing to analyze.")
        return

    vhm = header_map(v_header)

    now = utcnow()
    cutoff = now - timedelta(days=RECENT_DAYS)

    recent_rows: List[List[str]] = []
    baseline_rows: List[List[str]] = []

    for r in v_rows:
        dt = (
            parse_dt(pick(r, vhm, "last_scored_at"))
            or parse_dt(pick(r, vhm, "scraped_at"))
            or None
        )
        if dt is None:
            # no timestamps -> treat as recent for MVP
            recent_rows.append(r)
        else:
            if dt >= cutoff:
                recent_rows.append(r)
            else:
                baseline_rows.append(r)

    print(f"[INFO] Total videos: {len(v_rows)}")
    print(f"[INFO] Recent: {len(recent_rows)} Baseline: {len(baseline_rows)} (cutoff={cutoff.isoformat()})")

    # ---------- NICHE STATS ----------
    rec: Dict[str, List[float]] = {}
    base: Dict[str, List[float]] = {}

    for r in recent_rows:
        niche = clean_text(pick(r, vhm, "niche"))
        if not niche:
            continue
        eng = safe_float(pick(r, vhm, "engagement_metric"), 0.0)
        rec.setdefault(niche, []).append(eng)

    for r in baseline_rows:
        niche = clean_text(pick(r, vhm, "niche"))
        if not niche:
            continue
        eng = safe_float(pick(r, vhm, "engagement_metric"), 0.0)
        base.setdefault(niche, []).append(eng)

    niche_rows_out: List[List[Any]] = []
    all_niches = set(rec.keys()) | set(base.keys())

    for niche in sorted(all_niches):
        rxs = rec.get(niche, [])
        bxs = base.get(niche, [])
        recent_avg = mean(rxs)
        base_avg = mean(bxs)
        heat = (recent_avg - base_avg) if base_avg > 0 else recent_avg

        niche_rows_out.append([
            niche,
            round(heat, 3),
            len(rxs),
            round(recent_avg, 3),
            round(base_avg, 3),
        ])

    niche_rows_out.sort(key=lambda x: float(x[1]), reverse=True)

    niche_header = ["niche", "heat_score", "recent_videos", "recent_avg_eng", "baseline_avg_eng"]
    write_sheet(niche_ws, niche_header, niche_rows_out)
    print("[OK] niche_stats updated")

    # ---------- HASHTAG HISTORY ----------
    rec_h: Dict[str, int] = {}
    base_h: Dict[str, int] = {}

    for r in recent_rows:
        tags = extract_hashtags(pick(r, vhm, "hashtags"))
        for t in tags:
            rec_h[t] = rec_h.get(t, 0) + 1

    for r in baseline_rows:
        tags = extract_hashtags(pick(r, vhm, "hashtags"))
        for t in tags:
            base_h[t] = base_h.get(t, 0) + 1

    all_tags = set(rec_h.keys()) | set(base_h.keys())
    hashtag_rows_out: List[List[Any]] = []

    for tag in all_tags:
        rc = rec_h.get(tag, 0)
        bc = base_h.get(tag, 0)
        vel = rc - bc
        hashtag_rows_out.append([tag, vel, rc, bc])

    hashtag_rows_out.sort(key=lambda x: (int(x[1]), int(x[2])), reverse=True)

    hashtag_header = ["hashtag", "velocity", "recent_count", "baseline_count"]
    write_sheet(hashtag_ws, hashtag_header, hashtag_rows_out)
    print("[OK] hashtag_history updated")


if __name__ == "__main__":
    main()

