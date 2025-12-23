"""
score_agent.py

Scores TikTok videos in the "videos" Google Sheet.

Behavior (MVP-friendly):
- Reads rows from the "videos" sheet.
- ONLY processes rows where status is "" or "NEW" (case-insensitive).
- Computes:
    - engagement_metric = likes + comments + shares + favorites
    - viral_score (0–100) based on shares/comments/favorites per like
    - engagement_score (0–1)
    - hashtag_score (0–1)
    - niche_heat_score (0–1 placeholder for now)
    - suggestions (human-friendly)
    - last_scored_at (ISO timestamp)
- Writes results back to the SAME row.
- Sets status = "DONE"

Notes:
- This is intentionally deterministic + lightweight.
- It does NOT call OpenAI. (Your upload_analyze endpoint is where AI happens.)
"""

import os
import time
import logging
import traceback
from datetime import datetime, UTC
from typing import Dict, Any, List, Tuple

import gspread


# ==============================
# CONFIG
# ==============================

GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "1XNkTaG02oj76pzxt_TC0-o2ug7zTbpSJl3FK5k2jpXQ")
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json")
VIDEOS_SHEET_NAME = os.getenv("VIDEOS_SHEET_NAME", "videos")

# Optional controls
MAX_ROWS_PER_RUN = int(os.getenv("MAX_ROWS_PER_RUN", "0"))  # 0 = unlimited
SLEEP_BETWEEN_WRITES_SEC = float(os.getenv("SLEEP_BETWEEN_WRITES_SEC", "0.8"))

LOG_FILE = os.path.join(os.path.dirname(__file__), "logs", "score_agent.log")
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
console = logging.StreamHandler()
console.setLevel(logging.INFO)
console.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logging.getLogger().addHandler(console)


# ==============================
# GOOGLE SHEETS HELPERS
# ==============================

def get_gsheets_client() -> gspread.Client:
    logging.info("Authenticating with Google Sheets using %s", GOOGLE_SERVICE_ACCOUNT_FILE)
    return gspread.service_account(filename=GOOGLE_SERVICE_ACCOUNT_FILE)


def get_worksheet(client: gspread.Client, sheet_name: str) -> gspread.Worksheet:
    sh = client.open_by_key(GOOGLE_SHEET_ID)
    return sh.worksheet(sheet_name)


def normalize_header(header_row: List[str]) -> Dict[str, int]:
    mapping: Dict[str, int] = {}
    for idx, name in enumerate(header_row):
        norm = (name or "").strip().lower()
        if norm:
            mapping[norm] = idx
    return mapping


def ensure_column(ws: gspread.Worksheet, header_row: List[str], header_map: Dict[str, int], column_name: str) -> Tuple[List[str], Dict[str, int]]:
    norm = column_name.strip().lower()
    if norm in header_map:
        return header_row, header_map

    header_row.append(column_name)
    # Update header row in-place
    ws.update(values=[header_row], range_name="1:1")
    logging.info("Added missing column '%s' to videos header.", column_name)
    return header_row, normalize_header(header_row)


def safe_int(value: Any) -> int:
    try:
        if value is None:
            return 0
        s = str(value).replace(",", "").strip()
        if not s:
            return 0
        return int(float(s))
    except Exception:
        return 0


def safe_str(value: Any) -> str:
    return ("" if value is None else str(value)).strip()


# ==============================
# SCORING LOGIC
# ==============================

def extract_metrics(row: List[str], header_map: Dict[str, int]) -> Dict[str, Any]:
    def get_col(*names: str, default: str = "") -> str:
        for n in names:
            idx = header_map.get(n.strip().lower())
            if idx is not None and idx < len(row):
                v = row[idx]
                if v is not None and str(v).strip() != "":
                    return str(v)
        return default

    likes = safe_int(get_col("likes", "like_count", "like-count"))
    comments = safe_int(get_col("comments", "comment_count", "comment-count"))
    shares = safe_int(get_col("shares", "share_count", "share-count"))
    favorites = safe_int(get_col("favorites", "favorite_count", "favorite-count", "saves"))

    metrics = {
        "likes": likes,
        "comments": comments,
        "shares": shares,
        "favorites": favorites,
        "engagement_metric": likes + comments + shares + favorites,
        "niche": get_col("niche", default=""),
        "url": get_col("url", default=""),
        "title": get_col("title", "video_title", default=""),
        "hashtags_raw": get_col("hashtags", "caption", "description", default=""),
    }
    return metrics


def calculate_scores(metrics: Dict[str, Any]) -> Dict[str, Any]:
    likes = int(metrics["likes"])
    comments = int(metrics["comments"])
    shares = int(metrics["shares"])
    favorites = int(metrics["favorites"])
    hashtags_raw = metrics.get("hashtags_raw") or ""

    base_likes = max(likes, 1)  # avoid div by zero

    shares_per_like = shares / base_likes
    comments_per_like = comments / base_likes
    favorites_per_like = favorites / base_likes

    # Weighted “virality” proxy (share-heavy)
    raw_score = (3.0 * shares_per_like) + (2.0 * comments_per_like) + (1.0 * favorites_per_like)

    # Scale raw_score to 0–100
    # raw_score ~2.5 -> 100
    scale_factor = 40.0
    viral_score = max(0.0, min(100.0, raw_score * scale_factor))
    viral_score = round(viral_score, 2)

    engagement_score = round(viral_score / 100.0, 3)

    hashtag_count = hashtags_raw.count("#")
    hashtag_score = round(min(1.0, hashtag_count / 5.0), 3)

    # Placeholder until you plug in niche_stats / analyze_trends outputs
    niche_heat_score = round(0.5, 3)

    suggestions: List[str] = []

    if shares_per_like < 0.05:
        suggestions.append("Shares per like are low. Make the payoff more shareable (surprising, funny, or highly useful).")
    elif shares_per_like < 0.15:
        suggestions.append("Shares per like are decent. Add stronger CTAs like “send this to a friend who…” to lift shares.")
    else:
        suggestions.append("Shares per like are strong. Double down on this format and keep testing hooks.")

    if comments_per_like < 0.05:
        suggestions.append("Comments per like are low. Ask a direct question or invite opinions in caption/on-screen text.")
    elif comments_per_like < 0.15:
        suggestions.append("Comments per like are okay. Try “which one are you?” or a polarizing question to spark replies.")
    else:
        suggestions.append("Comments per like are strong. You’re sparking conversation—great algorithm signal.")

    if favorites_per_like < 0.10:
        suggestions.append("Saves per like are low. Add “save this for later” value: steps, checklists, recipes, quick tips.")
    else:
        suggestions.append("Saves per like look good. People want to come back to this—keep that pattern.")

    if hashtag_count == 0:
        suggestions.append("Add 3–5 niche-relevant hashtags so TikTok can classify the video.")
    elif hashtag_score < 0.4:
        suggestions.append("Use 3–5 relevant hashtags mixing broad (#fyp) + niche tags + specific long-tail tags.")
    else:
        suggestions.append("Hashtag usage looks fine. Next improvement: first 1–3 seconds + pacing.")

    return {
        "viral_score": viral_score,
        "engagement_metric": int(metrics.get("engagement_metric", 0)),
        "engagement_score": engagement_score,
        "hashtag_score": hashtag_score,
        "niche_heat_score": niche_heat_score,
        "suggestions_text": " | ".join(suggestions),
    }


# ==============================
# MAIN
# ==============================

def run_scorer() -> None:
    logging.info("=== Score agent run started ===")

    client = get_gsheets_client()
    ws = get_worksheet(client, VIDEOS_SHEET_NAME)

    rows = ws.get_all_values()
    if not rows:
        logging.warning("Videos sheet is empty. Nothing to score.")
        return

    header_row = rows[0]
    header_map = normalize_header(header_row)

    required_cols = [
        "status",
        "viral_score",
        "engagement_metric",
        "engagement_score",
        "hashtag_score",
        "niche_heat_score",
        "suggestions",
        "last_scored_at",
    ]

    for col in required_cols:
        header_row, header_map = ensure_column(ws, header_row, header_map, col)

    # Refresh after header changes
    rows = ws.get_all_values()
    header_row = rows[0]
    header_map = normalize_header(header_row)

    status_idx = header_map.get("status")
    viral_idx = header_map["viral_score"]
    eng_metric_idx = header_map["engagement_metric"]
    engagement_idx = header_map["engagement_score"]
    hashtag_idx = header_map["hashtag_score"]
    niche_heat_idx = header_map["niche_heat_score"]
    suggestions_idx = header_map["suggestions"]
    last_scored_idx = header_map["last_scored_at"]

    processed = 0
    considered = 0

    for row_number in range(2, len(rows) + 1):
        row = rows[row_number - 1]

        # status check
        status_val = ""
        if status_idx is not None and status_idx < len(row):
            status_val = safe_str(row[status_idx]).upper()

        if status_val not in ("", "NEW"):
            continue

        considered += 1

        try:
            metrics = extract_metrics(row, header_map)
            scores = calculate_scores(metrics)

            required_len = max(
                status_idx or 0,
                viral_idx,
                eng_metric_idx,
                engagement_idx,
                hashtag_idx,
                niche_heat_idx,
                suggestions_idx,
                last_scored_idx,
            ) + 1

            if len(row) < required_len:
                row.extend([""] * (required_len - len(row)))

            row[viral_idx] = str(scores["viral_score"])
            row[eng_metric_idx] = str(scores["engagement_metric"])
            row[engagement_idx] = str(scores["engagement_score"])
            row[hashtag_idx] = str(scores["hashtag_score"])
            row[niche_heat_idx] = str(scores["niche_heat_score"])
            row[suggestions_idx] = scores["suggestions_text"]
            row[last_scored_idx] = datetime.now(UTC).isoformat()
            if status_idx is not None:
                row[status_idx] = "DONE"

            ws.update(values=[row], range_name=f"{row_number}:{row_number}")
            processed += 1

            logging.info(
                "Scored row %s url=%s viral_score=%s engagement_metric=%s",
                row_number,
                metrics.get("url", ""),
                scores["viral_score"],
                scores["engagement_metric"],
            )

            if MAX_ROWS_PER_RUN and processed >= MAX_ROWS_PER_RUN:
                logging.info("Hit MAX_ROWS_PER_RUN=%d. Stopping.", MAX_ROWS_PER_RUN)
                break

            time.sleep(SLEEP_BETWEEN_WRITES_SEC)

        except Exception as e:
            logging.error("Error scoring row %s: %s", row_number, e)
            logging.error(traceback.format_exc())

    logging.info("=== Score agent finished. considered=%d processed=%d ===", considered, processed)


def main() -> None:
    try:
        run_scorer()
    except Exception as e:
        logging.error("Fatal error in score_agent: %s", e)
        logging.error(traceback.format_exc())
        raise


if __name__ == "__main__":
    main()

