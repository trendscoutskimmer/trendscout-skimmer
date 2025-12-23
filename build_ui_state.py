import os
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import gspread


# =========================
# CONFIG
# =========================
SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json")
SHEET_ID = os.getenv("GOOGLE_SHEET_ID") or os.getenv("SHEET_ID")

VIDEOS_SHEET = os.getenv("VIDEOS_SHEET", "videos")
NICHE_STATS_SHEET = os.getenv("NICHE_STATS_SHEET", "niche_stats")
HASHTAG_HISTORY_SHEET = os.getenv("HASHTAG_HISTORY_SHEET", "hashtag_history")
CREATORS_SHEET = os.getenv("CREATORS_SHEET", "creators")
UI_STATE_SHEET = os.getenv("UI_STATE_SHEET", "ui_state")

UI_STATE_ID = "latest"
SCHEMA_VERSION = "ui_state_v1_summary"

# Stay under Sheets 50k per-cell limit (give yourself buffer)
MAX_CELL_CHARS = int(os.getenv("UI_STATE_MAX_CHARS", "49000"))

# How much to include in summary
TOP_HASHTAGS = int(os.getenv("UI_TOP_HASHTAGS", "20"))
TOP_NICHES = int(os.getenv("UI_TOP_NICHES", "20"))
TOP_CREATORS = int(os.getenv("UI_TOP_CREATORS", "20"))
RECENT_VIDEOS = int(os.getenv("UI_RECENT_VIDEOS", "20"))


# =========================
# HELPERS
# =========================
def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def gs_client():
    if not SHEET_ID:
        raise RuntimeError("Missing GOOGLE_SHEET_ID env var.")
    return gspread.service_account(filename=SERVICE_ACCOUNT_FILE).open_by_key(SHEET_ID)


def safe_int(x: Any, default: int = 0) -> int:
    try:
        if x is None:
            return default
        s = str(x).strip()
        if s == "":
            return default
        # remove commas
        s = s.replace(",", "")
        return int(float(s))
    except Exception:
        return default


def safe_float(x: Any, default: float = 0.0) -> float:
    try:
        if x is None:
            return default
        s = str(x).strip()
        if s == "":
            return default
        s = s.replace(",", "")
        return float(s)
    except Exception:
        return default


def clean_text(s: Any) -> str:
    if s is None:
        return ""
    out = str(s).strip()
    # common “weird sheet export” artifacts
    out = out.replace("\u00a0", " ")
    return out


def clean_hashtag(s: Any) -> str:
    t = clean_text(s)
    # remove trailing commas users were seeing in UI (e.g. "#purse tok,")
    t = t.rstrip(",")
    return t


def header_map(header_row: List[str]) -> Dict[str, int]:
    """
    Map normalized header -> index
    Normalization: lower + strip
    """
    m = {}
    for i, h in enumerate(header_row):
        key = clean_text(h).lower()
        if key:
            m[key] = i
    return m


def get_ws(sh, title: str):
    try:
        return sh.worksheet(title)
    except Exception:
        # Create if missing (nice for MVP)
        return sh.add_worksheet(title=title, rows=1000, cols=20)


def ws_all_rows(ws) -> Tuple[List[str], List[List[str]]]:
    rows = ws.get_all_values()
    if not rows:
        return [], []
    header = rows[0]
    data = rows[1:] if len(rows) > 1 else []
    return header, data


def pick(row: List[str], hm: Dict[str, int], key: str, default: str = "") -> str:
    idx = hm.get(key)
    if idx is None:
        return default
    return row[idx] if idx < len(row) else default


def upsert_ui_state(ws, row_id: str, schema_version: str, payload_json: str) -> None:
    """
    ui_state expected columns:
    A: id
    B: updated_at
    C: schema_version
    D: payload_json
    """
    header, data = ws_all_rows(ws)
    hm = header_map(header) if header else {}

    # Ensure header exists
    expected = ["id", "updated_at", "schema_version", "payload_json"]
    if not header or [clean_text(x).lower() for x in header[:4]] != expected:
        ws.clear()
        ws.update(range_name="A1:D1", values=[expected], value_input_option="RAW")
        header = expected
        data = []

    # Find row with id
    target_row_idx = None
    for i, r in enumerate(data, start=2):  # sheet rows start at 1, data starts at row 2
        if len(r) > 0 and clean_text(r[0]) == row_id:
            target_row_idx = i
            break

    updated_at = utcnow_iso()
    values = [[row_id, updated_at, schema_version, payload_json]]

    if target_row_idx is None:
        ws.append_row(values[0], value_input_option="RAW")
    else:
        ws.update(
            range_name=f"A{target_row_idx}:D{target_row_idx}",
            values=values,
            value_input_option="RAW",
        )


# =========================
# BUILD SUMMARY PAYLOAD
# =========================
def build_payload(sh) -> Dict[str, Any]:
    # ---- Read sheets
    videos_ws = get_ws(sh, VIDEOS_SHEET)
    niche_ws = get_ws(sh, NICHE_STATS_SHEET)
    hashtag_ws = get_ws(sh, HASHTAG_HISTORY_SHEET)
    creators_ws = get_ws(sh, CREATORS_SHEET)

    v_header, v_rows = ws_all_rows(videos_ws)
    n_header, n_rows = ws_all_rows(niche_ws)
    h_header, h_rows = ws_all_rows(hashtag_ws)
    c_header, c_rows = ws_all_rows(creators_ws)

    vhm = header_map(v_header)
    nhm = header_map(n_header)
    hhm = header_map(h_header)
    chm = header_map(c_header)

    # ---- Counts
    distinct_niches = set()
    for r in v_rows:
        niche = clean_text(pick(r, vhm, "niche"))
        if niche:
            distinct_niches.add(niche)

    counts = {
        "videos": len(v_rows),
        "creators": len(c_rows),
        "niches": len(distinct_niches) if distinct_niches else len(n_rows),
        "hashtags": len(h_rows),
    }

    # ---- Top hashtags from hashtag_history (by velocity)
    hashtags = []
    for r in h_rows:
        tag = clean_hashtag(pick(r, hhm, "hashtag"))
        if not tag:
            continue
        hashtags.append({
            "hashtag": tag,
            "velocity": safe_float(pick(r, hhm, "velocity"), 0.0),
            "recent_count": safe_int(pick(r, hhm, "recent_count"), 0),
            "baseline_count": safe_int(pick(r, hhm, "baseline_count"), 0),
        })
    hashtags.sort(key=lambda x: x["velocity"], reverse=True)
    top_hashtags = hashtags[:TOP_HASHTAGS]

    # ---- Top niches from niche_stats (by heat_score)
    niches = []
    for r in n_rows:
        niche_name = clean_text(pick(r, nhm, "niche"))
        if not niche_name:
            continue

        # Guardrail: prevent numeric IDs (video_id) from ever becoming "niche"
        # If it's mostly digits and very long, skip it.
        compact = niche_name.replace(" ", "")
        if compact.isdigit() and len(compact) >= 15:
            continue

        niches.append({
            "niche": niche_name,
            "heat_score": safe_float(pick(r, nhm, "heat_score"), 0.0),
            "recent_videos": safe_int(pick(r, nhm, "recent_videos"), 0),
            "recent_avg_eng": safe_float(pick(r, nhm, "recent_avg_eng"), 0.0),
            "baseline_avg_eng": safe_float(pick(r, nhm, "baseline_avg_eng"), 0.0),
        })
    niches.sort(key=lambda x: x["heat_score"], reverse=True)
    top_niches = niches[:TOP_NICHES]

    # ---- Top creators: compute from videos (reliable), enrich with creators sheet if present
    creator_meta = {}
    for r in c_rows:
        username = clean_text(pick(r, chm, "username"))
        if not username:
            continue
        creator_meta[username.lower()] = {
            "username": username,
            "profile_url": clean_text(pick(r, chm, "profile_url")),
            "display_name": clean_text(pick(r, chm, "display_name")),
            "followers": safe_int(pick(r, chm, "followers"), 0),
            "likes": safe_int(pick(r, chm, "likes"), 0),
            "bio": clean_text(pick(r, chm, "bio")),
            "niches": clean_text(pick(r, chm, "niches")),
        }

    agg: Dict[str, Dict[str, Any]] = {}
    for r in v_rows:
        username = clean_text(pick(r, vhm, "creator_username")) or clean_text(pick(r, vhm, "creator"))
        if not username:
            continue
        key = username.lower()
        if key not in agg:
            agg[key] = {
                "username": username,
                "video_count": 0,
                "sum_eng": 0.0,
                "sum_viral": 0.0,
                "profile_url": clean_text(pick(r, vhm, "creator_profile_url")),
                "followers": 0,
            }
        agg[key]["video_count"] += 1
        agg[key]["sum_eng"] += safe_float(pick(r, vhm, "engagement_metric"), 0.0)
        agg[key]["sum_viral"] += safe_float(pick(r, vhm, "viral_score"), 0.0)

    creators = []
    for key, a in agg.items():
        vc = max(1, a["video_count"])
        avg_eng = a["sum_eng"] / vc
        avg_viral = a["sum_viral"] / vc

        meta = creator_meta.get(key, {})
        followers = meta.get("followers", 0) or a.get("followers", 0)

        creators.append({
            "username": meta.get("username") or a["username"],
            "profile_url": meta.get("profile_url") or a.get("profile_url") or "",
            "followers": followers,
            "video_count": a["video_count"],
            "avg_engagement_metric": round(avg_eng, 2),
            "avg_viral_score": round(avg_viral, 2),
        })

    creators.sort(key=lambda x: (x["avg_engagement_metric"], x["video_count"]), reverse=True)
    top_creators = creators[:TOP_CREATORS]

    # ---- Recent videos: sort by last_scored_at if present; else take last rows
    videos_out = []
    for r in v_rows:
        video_id = clean_text(pick(r, vhm, "video_id"))
        url = clean_text(pick(r, vhm, "url"))
        if not url:
            continue
        videos_out.append({
            "video_id": video_id,
            "url": url,
            "title": clean_text(pick(r, vhm, "title")),
            "niche": clean_text(pick(r, vhm, "niche")),
            "creator_username": clean_text(pick(r, vhm, "creator_username")),
            "engagement_metric": safe_float(pick(r, vhm, "engagement_metric"), 0.0),
            "viral_score": safe_float(pick(r, vhm, "viral_score"), 0.0),
            "last_scored_at": clean_text(pick(r, vhm, "last_scored_at")),
        })

    def sort_key(v):
        # ISO sorts lexicographically, fallback to empty
        return v.get("last_scored_at") or ""

    videos_out.sort(key=sort_key, reverse=True)
    recent_videos = videos_out[:RECENT_VIDEOS]

    payload = {
        "generated_at": utcnow_iso(),
        "schema": SCHEMA_VERSION,
        "counts": counts,
        "top_hashtags": top_hashtags,
        "top_niches": top_niches,
        "top_creators": top_creators,
        "recent_videos": recent_videos,
    }
    return payload


def main():
    print("[INFO] Connecting to Google Sheets…")
    sh = gs_client()

    print("[INFO] Building UI summary payload…")
    payload = build_payload(sh)
    payload_json = json.dumps(payload, ensure_ascii=False)

    print(f"[INFO] ui_state payload size: {len(payload_json)} chars (limit {MAX_CELL_CHARS})")
    if len(payload_json) > MAX_CELL_CHARS:
        # last-resort trimming
        payload["recent_videos"] = payload.get("recent_videos", [])[:10]
        payload["top_hashtags"] = payload.get("top_hashtags", [])[:10]
        payload["top_niches"] = payload.get("top_niches", [])[:10]
        payload["top_creators"] = payload.get("top_creators", [])[:10]
        payload_json = json.dumps(payload, ensure_ascii=False)
        print(f"[WARN] Trimmed ui_state payload to {len(payload_json)} chars")
        if len(payload_json) > MAX_CELL_CHARS:
            raise RuntimeError("ui_state payload still too large after trimming")

    ui_ws = get_ws(sh, UI_STATE_SHEET)

    print("[INFO] Writing ui_state payload…")
    upsert_ui_state(ui_ws, UI_STATE_ID, SCHEMA_VERSION, payload_json)

    print("[OK] ui_state updated successfully ✅")


if __name__ == "__main__":
    main()

