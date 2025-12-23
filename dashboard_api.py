import os
import re
from datetime import datetime
from typing import List, Dict, Any, Optional

import gspread
from fastapi import (
    FastAPI,
    Query,
    HTTPException,
    UploadFile,
    File,
    Form,
    Body,
)
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

# OpenAI for AI-powered title suggestions
try:
    from openai import OpenAI  # type: ignore
except ImportError:  # library not installed yet
    OpenAI = None  # type: ignore

# ==============================
# CONFIG
# ==============================

BASE_DIR = os.path.dirname(__file__)
GOOGLE_SHEET_ID = "1XNkTaG02oj76pzxt_TC0-o2ug7zTbpSJl3FK5k2jpXQ"
GOOGLE_SERVICE_ACCOUNT_FILE = os.path.join(BASE_DIR, "service_account.json")

VIDEOS_SHEET_NAME = "videos"
CREATORS_SHEET_NAME = "creators"

UI_FILE = os.path.join(BASE_DIR, "ui.html")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")

os.makedirs(UPLOAD_DIR, exist_ok=True)

OPENAI_MODEL_FOR_TITLES = "gpt-4o-mini"  # cheap + good


# ==============================
# OPENAI CLIENT HELPER
# ==============================

_openai_client: Optional["OpenAI"] = None  # type: ignore


def get_openai_client():
    """
    Return a cached OpenAI client if:
      - the openai library is installed, and
      - OPENAI_API_KEY is set.
    Otherwise return None and we'll fall back to heuristic titles.
    """
    global _openai_client
    if _openai_client is not None:
        return _openai_client

    if OpenAI is None:
        return None

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    try:
        _openai_client = OpenAI()
        return _openai_client
    except Exception:
        return None


# ==============================
# GOOGLE SHEETS HELPERS
# ==============================

def get_gsheets_client():
    return gspread.service_account(filename=GOOGLE_SERVICE_ACCOUNT_FILE)


def normalize_header(header_row: List[str]) -> Dict[str, int]:
    mapping: Dict[str, int] = {}
    for idx, name in enumerate(header_row):
        norm = name.strip().lower()
        if norm:
            mapping[norm] = idx
    return mapping


def read_sheet(ws) -> (List[str], List[List[str]]):
    rows = ws.get_all_values()
    if not rows:
        return [], []
    header = rows[0]
    data = rows[1:]
    return header, data


# ==============================
# SHEET DATA LOADERS
# ==============================

def load_videos(gc) -> Dict[str, Any]:
    """Load videos sheet as structured dicts."""
    sh = gc.open_by_key(GOOGLE_SHEET_ID)
    ws = sh.worksheet(VIDEOS_SHEET_NAME)
    header, data = read_sheet(ws)
    if not header:
        return {"header": [], "rows": []}

    hmap = normalize_header(header)

    niche_idx = hmap.get("niche")
    url_idx = hmap.get("url")
    viral_idx = hmap.get("viral_score")
    shares_like_idx = hmap.get("shares_per_like")
    comments_like_idx = hmap.get("comments_per_like")
    favorites_like_idx = hmap.get("favorites_per_like")
    last_scored_idx = hmap.get("last_scored")
    hashtags_idx = hmap.get("hashtags") or hmap.get("tags")

    rows_parsed = []
    for row in data:
        while len(row) < len(header):
            row.append("")

        try:
            niche = (row[niche_idx] if niche_idx is not None else "").strip()
            url = (row[url_idx] if url_idx is not None else "").strip()
            viral_str = row[viral_idx] if viral_idx is not None else ""
            if not niche or not url or not viral_str:
                continue
            viral_score = float(viral_str)
        except Exception:
            continue

        def safe_float(i: Optional[int]) -> Optional[float]:
            if i is None:
                return None
            try:
                s = row[i].strip()
                if not s:
                    return None
                return float(s)
            except Exception:
                return None

        shares_pl = safe_float(shares_like_idx)
        comments_pl = safe_float(comments_like_idx)
        favs_pl = safe_float(favorites_like_idx)
        last_scored = (
            row[last_scored_idx].strip()
            if last_scored_idx is not None and last_scored_idx < len(row)
            else ""
        )
        hashtags_raw = (
            row[hashtags_idx].strip()
            if hashtags_idx is not None and hashtags_idx < len(row)
            else ""
        )

        rows_parsed.append(
            {
                "niche": niche,
                "url": url,
                "viral_score": viral_score,
                "shares_per_like": shares_pl,
                "comments_per_like": comments_pl,
                "favorites_per_like": favs_pl,
                "last_scored": last_scored,
                "hashtags_raw": hashtags_raw,
            }
        )

    return {"header": header, "rows": rows_parsed}


def load_creators(gc) -> Dict[str, Any]:
    """Load creators sheet as structured dicts."""
    sh = gc.open_by_key(GOOGLE_SHEET_ID)
    try:
        ws = sh.worksheet(CREATORS_SHEET_NAME)
    except gspread.exceptions.WorksheetNotFound:
        return {"header": [], "rows": []}

    header, data = read_sheet(ws)
    if not header:
        return {"header": [], "rows": []}

    hmap = normalize_header(header)

    username_idx = hmap.get("username")
    profile_url_idx = hmap.get("profile_url")
    display_name_idx = hmap.get("display_name")
    followers_idx = hmap.get("followers")
    following_idx = hmap.get("following")
    likes_idx = hmap.get("likes")
    bio_idx = hmap.get("bio")
    niches_idx = hmap.get("niches")
    last_updated_idx = hmap.get("last_updated")

    rows_parsed = []
    for row in data:
        while len(row) < len(header):
            row.append("")

        username = (row[username_idx] if username_idx is not None else "").strip()
        profile_url = (row[profile_url_idx] if profile_url_idx is not None else "").strip()
        if not username:
            continue

        def safe_int(i: Optional[int]) -> int:
            if i is None:
                return 0
            try:
                s = row[i].replace(",", "").strip()
                if not s:
                    return 0
                return int(float(s))
            except Exception:
                return 0

        followers = safe_int(followers_idx)
        following = safe_int(following_idx)
        likes = safe_int(likes_idx)
        display_name = row[display_name_idx].strip() if display_name_idx is not None else ""
        bio = row[bio_idx].strip() if bio_idx is not None else ""
        niches_str = row[niches_idx].strip() if niches_idx is not None else ""
        last_updated = row[last_updated_idx].strip() if last_updated_idx is not None else ""

        rows_parsed.append(
            {
                "username": username,
                "profile_url": profile_url,
                "display_name": display_name,
                "followers": followers,
                "following": following,
                "likes": likes,
                "bio": bio,
                "niches": [n.strip() for n in niches_str.split(",") if n.strip()],
                "last_updated": last_updated,
            }
        )

    return {"header": header, "rows": rows_parsed}


# ==============================
# HASHTAGS
# ==============================

HASHTAG_REGEX = re.compile(r"#?([a-zA-Z0-9_]+)")


def parse_hashtags(text: str) -> List[str]:
    if not text:
        return []
    tokens = HASHTAG_REGEX.findall(text.lower())
    seen = set()
    result: List[str] = []
    for t in tokens:
        if not t:
            continue
        if t not in seen:
            seen.add(t)
            result.append(t)
    return result


# ==============================
# DASHBOARD AGGREGATION
# ==============================

def compute_niche_stats(videos: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute basic stats for the given set of videos."""
    count = len(videos)
    if count == 0:
        return {"video_count": 0, "avg_viral_score": None, "top_hashtags": []}

    avg_viral = sum(v["viral_score"] for v in videos) / count

    hashtag_counts: Dict[str, int] = {}
    for v in videos:
        tags = parse_hashtags(v.get("hashtags_raw", ""))
        for t in tags:
            hashtag_counts[t] = hashtag_counts.get(t, 0) + 1

    top_sorted = sorted(hashtag_counts.items(), key=lambda kv: kv[1], reverse=True)
    top_tags = ["#" + tag for tag, _ in top_sorted[:10]]

    return {
        "video_count": count,
        "avg_viral_score": avg_viral,
        "top_hashtags": top_tags,
    }


def build_dashboard_data(
    niche: Optional[str] = None,
    max_items: int = 20,
) -> Dict[str, Any]:
    gc = get_gsheets_client()
    videos_data = load_videos(gc)
    creators_data = load_creators(gc)

    videos = videos_data["rows"]
    creators = creators_data["rows"]

    all_niches = sorted({v["niche"] for v in videos})

    niche_filter = niche.strip().lower() if niche else None
    if niche_filter:
        filtered_videos = [v for v in videos if v["niche"].lower() == niche_filter]
        filtered_creators = [
            c
            for c in creators
            if any(n.lower() == niche_filter for n in c.get("niches", []))
        ]
    else:
        filtered_videos = videos
        filtered_creators = creators

    total_videos = len(filtered_videos)
    total_creators = len(filtered_creators)

    # Last updated
    timestamps: List[str] = []
    for v in filtered_videos:
        ts = v.get("last_scored")
        if ts:
            timestamps.append(ts)
    for c in filtered_creators:
        ts = c.get("last_updated")
        if ts:
            timestamps.append(ts)

    latest_ts: Optional[datetime] = None
    for ts in timestamps:
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if latest_ts is None or dt > latest_ts:
                latest_ts = dt
        except Exception:
            continue

    last_updated = latest_ts.isoformat() if latest_ts else None

    # Top video per niche
    best_by_niche: Dict[str, Dict[str, Any]] = {}
    for v in filtered_videos:
        niche_name = v["niche"]
        if niche_name not in best_by_niche or v["viral_score"] > best_by_niche[niche_name]["viral_score"]:
            best_by_niche[niche_name] = v

    top_videos = sorted(
        best_by_niche.values(), key=lambda v: v["viral_score"], reverse=True
    )[:max_items]

    # Top creators
    top_creators = sorted(
        filtered_creators, key=lambda c: c["followers"], reverse=True
    )[:max_items]

    niche_stats = compute_niche_stats(filtered_videos)

    return {
        "summary": {
            "total_videos": total_videos,
            "total_creators": total_creators,
            "last_updated": last_updated,
        },
        "niches": all_niches,
        "selected_niche": niche,
        "top_videos": top_videos,
        "top_creators": top_creators,
        "niche_stats": niche_stats,
    }


# ==============================
# TITLE GENERATION
# ==============================

def generate_multi_tone_titles(
    niche: str,
    original_title: str,
    hashtags: List[str],
    niche_top_tags: List[str],
    global_trending_tags: List[str],
) -> List[Dict[str, str]]:
    """
    Generate 3 titles with tones: funny, serious, viral.
    Returns list of {tone, title}.
    """
    client = get_openai_client()
    tones = ["funny", "serious", "viral"]

    # ---------- Try OpenAI ----------
    if client is not None:
        try:
            niche_desc = niche or "general short-form video"
            tag_text = " ".join("#" + h for h in hashtags[:5])
            niche_tags_text = " ".join(niche_top_tags[:5])
            global_tags_text = " ".join("#" + t for t in global_trending_tags[:5])

            user_prompt = (
                "You're helping a creator go viral on TikTok / Reels / Shorts.\n\n"
                f"Niche: {niche_desc}\n"
                f"Current title/caption: {original_title or '(none provided)'}\n"
                f"Creator hashtags: {tag_text or '(none)'}\n"
                f"Top niche hashtags in our dataset: {niche_tags_text or '(none)'}\n"
                f"Globally trending hashtags: {global_tags_text or '(none)'}\n\n"
                "Produce EXACTLY 3 titles, one for each tone:\n"
                "- funny\n- serious\n- viral (hooky, high-click, very scroll-stopping)\n\n"
                "Return them in this exact format (one per line):\n"
                "funny: <title>\n"
                "serious: <title>\n"
                "viral: <title>\n"
                "Do not add any extra commentary."
            )

            resp = client.responses.create(
                model=OPENAI_MODEL_FOR_TITLES,
                input=[
                    {
                        "role": "system",
                        "content": (
                            "You are a viral short-form title generator. "
                            "You output only the requested lines and nothing else."
                        ),
                    },
                    {"role": "user", "content": user_prompt},
                ],
            )

            ai_text = getattr(resp, "output_text", None)
            if not ai_text:
                ai_text = str(resp.output[0].content[0].text)  # type: ignore

            lines = [ln.strip() for ln in ai_text.splitlines() if ln.strip()]
            results: List[Dict[str, str]] = []
            for ln in lines:
                for tone in tones:
                    prefix = f"{tone}:"
                    if ln.lower().startswith(prefix):
                        title = ln[len(prefix):].strip()
                        if title:
                            results.append({"tone": tone, "title": title})
                        break

            # Guarantee we have all tones if possible
            seen_tones = {r["tone"] for r in results}
            if len(seen_tones) == 3:
                return results
        except Exception:
            pass  # fall back below

    # ---------- Heuristic fallback ----------
    if niche:
        topic = niche
    elif hashtags:
        topic = hashtags[0].replace("_", " ")
    else:
        topic = "this"

    topic_phrase = topic.strip()
    if topic_phrase.lower().endswith("content"):
        topic_phrase = topic_phrase.rsplit(" ", 1)[0]

    results = [
        {
            "tone": "funny",
            "title": f"POV: you said, \"It's just {topic_phrase}, how bad can it be?\"",
        },
        {
            "tone": "serious",
            "title": f"The {topic_phrase} mistake that‘s quietly killing your results",
        },
        {
            "tone": "viral",
            "title": f"Watch this before you try another {topic_phrase} hack",
        },
    ]
    return results


def generate_titles_for_tone(
    tone: str,
    niche: str,
    original_title: str,
    hashtags: List[str],
    niche_top_tags: List[str],
    global_trending_tags: List[str],
) -> List[str]:
    """Generate more titles for a single tone (funny / serious / viral)."""
    tone = tone.lower().strip() or "viral"
    if tone not in {"funny", "serious", "viral"}:
        tone = "viral"

    client = get_openai_client()
    if client is not None:
        try:
            niche_desc = niche or "general short-form video"
            tag_text = " ".join("#" + h for h in hashtags[:5])
            niche_tags_text = " ".join(niche_top_tags[:5])
            global_tags_text = " ".join("#" + t for t in global_trending_tags[:5])

            user_prompt = (
                f"Niche: {niche_desc}\n"
                f"Existing title/caption: {original_title or '(none)'}\n"
                f"Hashtags: {tag_text or '(none)'}\n"
                f"Top niche hashtags: {niche_tags_text or '(none)'}\n"
                f"Global trending hashtags: {global_tags_text or '(none)'}\n\n"
                f"Generate 5 short-form video titles in a {tone} tone.\n"
                "- They should be optimized for TikTok / Reels / Shorts feeds.\n"
                "- Max ~80 characters.\n"
                "- Each on its own line.\n"
                "- Do not number them or add commentary."
            )

            resp = client.responses.create(
                model=OPENAI_MODEL_FOR_TITLES,
                input=[
                    {
                        "role": "system",
                        "content": (
                            "You are a viral short-form video title writer. "
                            "You output only raw titles, one per line."
                        ),
                    },
                    {"role": "user", "content": user_prompt},
                ],
            )

            ai_text = getattr(resp, "output_text", None)
            if not ai_text:
                ai_text = str(resp.output[0].content[0].text)  # type: ignore

            lines = [ln.strip(" -•\t") for ln in ai_text.splitlines()]
            titles = [ln for ln in lines if ln]
            return titles[:5]
        except Exception:
            pass

    # Fallback
    topic = niche or (hashtags[0].replace("_", " ") if hashtags else "this")
    topic_phrase = topic.strip()

    if tone == "funny":
        base = [
            f"POV: you tried {topic_phrase} once and now you're addicted",
            f"When they say 'it's just {topic_phrase}', but you know the truth",
            f"{topic_phrase} but make it a hot mess",
        ]
    elif tone == "serious":
        base = [
            f"The {topic_phrase} trick I wish I knew 3 years ago",
            f"No one is telling you this about {topic_phrase}",
            f"The brutal truth about {topic_phrase}",
        ]
    else:  # viral
        base = [
            f"Don’t scroll. This {topic_phrase} hack changes everything",
            f"Everyone’s doing this {topic_phrase} wrong (until now)",
            f"Watch this before your next {topic_phrase} video",
        ]
    return base


# ==============================
# UPLOAD & SCORING
# ==============================

def build_upload_recommendations(
    niche: str,
    title: str,
    hashtags_str: str,
) -> Dict[str, Any]:
    """
    Score uploaded video metadata using your dataset.

    Factors:
    - Niche average viral_score
    - Hashtag count quality
    - Match with niche hashtags
    - Match with global trending hashtags
    - Title length & quality
    - AI-powered multi-tone titles
    """
    gc = get_gsheets_client()
    videos_data = load_videos(gc)
    all_videos = videos_data["rows"]

    niche_clean = (niche or "").strip()
    title = (title or "").strip()
    hashtags_input = parse_hashtags(hashtags_str)

    # Niche filter
    if niche_clean:
        niche_videos = [v for v in all_videos if v["niche"].lower() == niche_clean.lower()]
    else:
        niche_videos = all_videos

    niche_video_count = len(niche_videos)

    if niche_video_count > 0:
        avg_viral = sum(v["viral_score"] for v in niche_videos) / niche_video_count
    else:
        avg_viral = 50.0

    # Hashtag frequencies
    niche_hashtag_counts: Dict[str, int] = {}
    global_hashtag_counts: Dict[str, int] = {}

    for v in all_videos:
        tags = parse_hashtags(v.get("hashtags_raw", ""))
        for t in tags:
            global_hashtag_counts[t] = global_hashtag_counts.get(t, 0) + 1

    for v in niche_videos:
        tags = parse_hashtags(v.get("hashtags_raw", ""))
        for t in tags:
            niche_hashtag_counts[t] = niche_hashtag_counts.get(t, 0) + 1

    top_niche_sorted = sorted(
        niche_hashtag_counts.items(), key=lambda kv: kv[1], reverse=True
    )
    top_niche_hashtags = ["#" + tag for tag, _ in top_niche_sorted[:10]]

    global_sorted = sorted(
        global_hashtag_counts.items(), key=lambda kv: kv[1], reverse=True
    )
    global_trending_tags = [tag for tag, _ in global_sorted[:30]]

    # ---- Raw score before compression ----
    score = float(avg_viral)
    notes: List[str] = []

    h_count = len(hashtags_input)
    if h_count == 0:
        score -= 15
        notes.append(
            "You're not using any hashtags. Most viral videos in this niche use 3–6 strong niche tags."
        )
    elif 1 <= h_count < 3:
        score += 3
        notes.append(
            f"You're using {h_count} hashtag(s). Consider 3–6 highly targeted tags for better discovery."
        )
    elif 3 <= h_count <= 6:
        score += 7
        notes.append(
            f"Your hashtag count ({h_count}) is right in the sweet spot for most viral videos."
        )
    elif 7 <= h_count <= 10:
        notes.append(
            f"You're using {h_count} hashtags. That's okay, but consider trimming to the best 3–6."
        )
    else:
        score -= 8
        notes.append(
            f"You're using {h_count} hashtags. That can look spammy; focus on the strongest 3–6."
        )

    # Niche hashtag overlap
    input_set = set(hashtags_input)
    niche_trending_raw = [h.lstrip("#").lower() for h in top_niche_hashtags]
    niche_trending_set = set(niche_trending_raw)
    matched_niche = input_set & niche_trending_set
    missing_niche = niche_trending_set - input_set

    if top_niche_hashtags and niche_video_count > 0:
        if matched_niche:
            bonus = min(len(matched_niche) * 2.0, 8.0)
            score += bonus
            notes.append(
                f"You're using {len(matched_niche)} of the strongest niche hashtags. Good alignment with what's working in this niche."
            )
        else:
            notes.append(
                "You're not using any of the strongest niche hashtags yet. Try adding 1–3 of the recommended niche tags."
            )

    # Global trending overlap (news, dances, etc.)
    global_trending_set = set(global_trending_tags)
    matched_global = input_set & global_trending_set
    if matched_global:
        bonus = min(len(matched_global) * 1.5, 6.0)
        score += bonus
        top_matched = ["#" + t for t in list(matched_global)[:3]]
        notes.append(
            f"You're tapping into globally trending topics: {' '.join(top_matched)}. This can help if the topic is hot right now."
        )

    # Niche dataset size
    if niche_clean and niche_video_count < 20:
        notes.append(
            f"This niche only has {niche_video_count} videos in your dataset so far. Recommendations will get smarter as more data is collected."
        )

    # Title quality
    if title:
        if len(title) < 20:
            notes.append(
                "Your title is short; consider adding a clearer hook or outcome to grab attention."
            )
        elif len(title) > 100:
            notes.append(
                "Your title is quite long; try tightening it to keep it punchy."
            )
    else:
        notes.append(
            "You didn't provide a title. A strong hook in the title/caption can significantly improve performance."
        )

    # ---- Compress & cap score so 100 is rare ----
    delta = score - avg_viral
    score = avg_viral + delta * 0.6  # compress movement

    if 3 <= h_count <= 6 and len(matched_niche) >= 1:
        score += 2.0
    if 3 <= h_count <= 6 and len(matched_global) >= 1:
        score += 1.0

    if niche_video_count < 20:
        max_cap = 92.0
    elif niche_video_count < 100:
        max_cap = 95.0
    else:
        max_cap = 97.0

    score = max(0.0, min(score, max_cap))

    missing_suggested_niche = ["#" + t for t in list(missing_niche)[:5]]

    # ---- Multi-tone AI titles ----
    multi_titles = generate_multi_tone_titles(
        niche_clean,
        title,
        hashtags_input,
        top_niche_hashtags,
        global_trending_tags,
    )
    # pick viral tone as recommended if available
    recommended = None
    for item in multi_titles:
        if item["tone"] == "viral":
            recommended = item["title"]
            break
    if recommended is None and multi_titles:
        recommended = multi_titles[0]["title"]

    return {
        "niche": niche_clean or None,
        "title": title,
        "hashtags_input": ["#" + h for h in hashtags_input],
        "score": round(score, 1),
        "niche_stats": {
            "avg_viral_score": round(avg_viral, 1),
            "video_count": niche_video_count,
            "top_hashtags": top_niche_hashtags,
        },
        "hashtag_recommendations": {
            "missing_suggested": missing_suggested_niche,
            "hashtag_count": h_count,
        },
        "notes": notes,
        "title_suggestions": multi_titles,
        "recommended_title": recommended,
        "global_trending_sample": ["#" + t for t in global_trending_tags[:10]],
    }


# ==============================
# FASTAPI APP
# ==============================

app = FastAPI(title="TrendScout Dashboard API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", response_class=FileResponse)
def serve_ui():
    return FileResponse(UI_FILE)


@app.get("/api/dashboard")
def api_dashboard(
    niche: Optional[str] = Query(None, description="Filter by niche name"),
    max_items: int = Query(20, ge=1, le=100),
):
    data = build_dashboard_data(niche=niche, max_items=max_items)
    return JSONResponse(content=data)


@app.post("/api/upload_score")
async def api_upload_score(
    file: UploadFile = File(...),
    niche: str = Form(""),
    title: str = Form(""),
    hashtags: str = Form(""),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="Video file is required.")

    ext = os.path.splitext(file.filename)[1] or ".mp4"
    safe_ext = ext if len(ext) < 10 else ".mp4"
    fname = datetime.utcnow().strftime("%Y%m%d%H%M%S") + safe_ext
    dest_path = os.path.join(UPLOAD_DIR, fname)

    contents = await file.read()
    with open(dest_path, "wb") as f:
        f.write(contents)

    try:
        result = build_upload_recommendations(niche, title, hashtags)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error scoring upload: {e}")

    result["stored_filename"] = fname
    return JSONResponse(content=result)


@app.post("/api/generate_titles")
async def api_generate_titles(
    payload: Dict[str, Any] = Body(...),
):
    """Generate more titles for a specific tone."""
    tone = (payload.get("tone") or "viral").lower()
    niche = payload.get("niche") or ""
    title = payload.get("title") or ""
    hashtags_str = payload.get("hashtags") or ""

    gc = get_gsheets_client()
    videos_data = load_videos(gc)
    all_videos = videos_data["rows"]

    # We'll compute hashtag stats based on niche
    niche_clean = niche.strip()
    if niche_clean:
        niche_videos = [v for v in all_videos if v["niche"].lower() == niche_clean.lower()]
    else:
        niche_videos = all_videos

    # Hashtag frequencies
    niche_hashtag_counts: Dict[str, int] = {}
    global_hashtag_counts: Dict[str, int] = {}

    for v in all_videos:
        tags = parse_hashtags(v.get("hashtags_raw", ""))
        for t in tags:
            global_hashtag_counts[t] = global_hashtag_counts.get(t, 0) + 1

    for v in niche_videos:
        tags = parse_hashtags(v.get("hashtags_raw", ""))
        for t in tags:
            niche_hashtag_counts[t] = niche_hashtag_counts.get(t, 0) + 1

    top_niche_sorted = sorted(
        niche_hashtag_counts.items(), key=lambda kv: kv[1], reverse=True
    )
    top_niche_hashtags = ["#" + tag for tag, _ in top_niche_sorted[:10]]

    global_sorted = sorted(
        global_hashtag_counts.items(), key=lambda kv: kv[1], reverse=True
    )
    global_trending_tags = [tag for tag, _ in global_sorted[:30]]

    hashtags_list = parse_hashtags(hashtags_str)

    titles = generate_titles_for_tone(
        tone,
        niche_clean,
        title,
        hashtags_list,
        top_niche_hashtags,
        global_trending_tags,
    )
    return JSONResponse(content={"tone": tone, "titles": titles})

