import os
import re
import json
import time
import subprocess
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple

import requests
from bs4 import BeautifulSoup

import gspread
from openai import OpenAI


# =========================
# CONFIG
# =========================
SERVICE_ACCOUNT_FILE = "service_account.json"

DEFAULT_SHEET_ID = "1XNkTaG02oj76pzxt_TC0-o2ug7zTbpSJl3FK5k2jpXQ"
SHEET_ID = os.getenv("GOOGLE_SHEET_ID") or DEFAULT_SHEET_ID

SHEET_VIDEOS = "videos"
SHEET_CREATORS = "creators"
SHEET_BLOG_POSTS = "blog_posts"
SHEET_TRANSCRIPTS = "transcripts"

TMP_DIR = "tmp_blog_agent"
os.makedirs(TMP_DIR, exist_ok=True)

# Limit per run to control cost
MAX_CREATORS_PER_RUN = int(os.getenv("BLOG_AGENT_MAX_CREATORS", "5"))

# Only use scored videos (recommended when scraper is running in parallel)
# Turn off with: export BLOG_AGENT_SCORED_ONLY="0"
ONLY_USE_SCORED_VIDEOS = os.getenv("BLOG_AGENT_SCORED_ONLY", "1") == "1"

# Network
REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0"}

# OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai_client = OpenAI(api_key=OPENAI_API_KEY)


# =========================
# SMALL HELPERS
# =========================
def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_username(u: str) -> str:
    return (u or "").strip().lower().lstrip("@").strip()


def slugify(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def parse_video_id(url: str) -> str:
    m = re.search(r"/video/(\d+)", url or "")
    return m.group(1) if m else ""


def safe_float(x) -> float:
    try:
        return float(str(x).strip() or 0)
    except Exception:
        return 0.0


def header_map(rows: List[List[str]]) -> Dict[str, int]:
    if not rows:
        return {}
    return {h.strip().lower(): i for i, h in enumerate(rows[0]) if h.strip()}


def get_cell(row: List[str], hm: Dict[str, int], col: str) -> str:
    i = hm.get(col)
    if i is None or i >= len(row):
        return ""
    return (row[i] or "").strip()


def get_sheet() -> gspread.Spreadsheet:
    gc = gspread.service_account(filename=SERVICE_ACCOUNT_FILE)
    return gc.open_by_key(SHEET_ID)


def ensure_headers(ws: gspread.Worksheet, expected_header: List[str]) -> None:
    values = ws.get_all_values()
    if not values:
        ws.append_row(expected_header, value_input_option="RAW")
        return
    current = [c.strip() for c in values[0]]
    if current != expected_header:
        raise RuntimeError(
            f"Header mismatch in sheet '{ws.title}'.\n"
            f"Expected:\n{expected_header}\n"
            f"Got:\n{current}\n"
            f"Fix the header row in Google Sheets or update expected header in the script."
        )


def fetch_og_image(url: str) -> str:
    """Best-effort: pull og:image (TikTok thumbnail). Returns empty string if blocked."""
    if not url:
        return ""
    try:
        r = requests.get(url, timeout=20, headers=REQUEST_HEADERS)
        if r.status_code != 200:
            return ""
        soup = BeautifulSoup(r.text, "html.parser")
        tag = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "twitter:image"})
        if tag and tag.get("content"):
            return tag["content"].strip()
    except Exception:
        return ""
    return ""


def yt_dlp_download_audio(video_url: str, video_id: str) -> Optional[str]:
    """
    Downloads audio and converts to mp3 using yt-dlp.
    Returns mp3 path or None.
    """
    if not video_url or not video_id:
        return None

    out_tpl = os.path.join(TMP_DIR, f"{video_id}.%(ext)s")
    cmd = [
        "yt-dlp",
        "-f", "bestaudio/best",
        "--extract-audio",
        "--audio-format", "mp3",
        "--audio-quality", "0",
        "-o", out_tpl,
        video_url,
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        return None

    mp3_path = os.path.join(TMP_DIR, f"{video_id}.mp3")
    return mp3_path if os.path.exists(mp3_path) else None


def openai_transcribe(mp3_path: str) -> str:
    """Whisper transcription."""
    with open(mp3_path, "rb") as f:
        tr = openai_client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
        )
    return (getattr(tr, "text", "") or "").strip()


# =========================
# BLOG GENERATION (IMPROVED QUALITY)
# =========================
def openai_generate_blog_json(payload: Dict[str, Any]) -> Dict[str, str]:
    """
    Returns dict with keys: title, meta_description, tags (comma string), markdown.
    """
    prompt = f"""
You are an expert TikTok growth analyst writing a data-driven breakdown of a real creator’s video.
Your tone is confident, practical, and analytical — not hype, not generic AI.

IMPORTANT RULES:
- Do NOT invent data.
- If a metric (like views) is missing, explicitly state it is not available.
- Base all analysis on the transcript and provided engagement metrics.
- Avoid vague phrases like "suggests" or "likely" unless uncertainty is unavoidable.
- Write clearly for creators who want to replicate what works.

STRUCTURE REQUIREMENTS:
Use the following sections and headings EXACTLY:

# Creator Snapshot
Brief factual overview using provided data only.

# Video Summary
Explain what happens in the video based on transcript content.

# Why This Video Works
Bullet points. Each bullet must reference either transcript behavior or engagement metrics.

# Niche Performance Context
Explain why this niche performs well using logic and engagement signals. Don't claim trends without proof.

# Actionable Takeaways
Numbered list. Clear, repeatable actions.

# Copy / Paste Content Template
Provide a short script structure creators can adapt.

# Hashtag Strategy
Explain how hashtags should be chosen. List 8–15 relevant hashtags.

# Final Analysis
Short conclusion tying performance + structure together.

OUTPUT FORMAT:
Return VALID JSON ONLY with keys:
- title (string, max ~70 chars)
- meta_description (string, max ~155 chars)
- tags (comma-separated string)
- markdown (string)

INPUT DATA:
{json.dumps(payload, ensure_ascii=False)}
"""

    resp = openai_client.responses.create(
        model="gpt-4.1-mini",
        input=prompt
    )
    text = (resp.output_text or "").strip()

    try:
        data = json.loads(text)
        return {
            "title": (data.get("title") or "").strip(),
            "meta_description": (data.get("meta_description") or "").strip(),
            "tags": (data.get("tags") or "").strip(),
            "markdown": (data.get("markdown") or "").strip(),
        }
    except Exception:
        # If model ever returns non-JSON, store it as markdown so you don't lose the output
        return {
            "title": "",
            "meta_description": "",
            "tags": "",
            "markdown": text
        }


# =========================
# SHEET READ/WRITE HELPERS
# =========================
def load_creators(creators_rows: List[List[str]]) -> List[Dict[str, Any]]:
    """
    creators sheet expected columns (based on your screenshot):
    username, profile_url, display_name, followers, bio, niches
    """
    hm = header_map(creators_rows)
    if "username" not in hm:
        raise RuntimeError("creators sheet must have a 'username' column")

    creators: List[Dict[str, Any]] = []
    for r in creators_rows[1:]:
        username = get_cell(r, hm, "username")
        if not username:
            continue
        creators.append({
            "username": username,
            "profile_url": get_cell(r, hm, "profile_url"),
            "display_name": get_cell(r, hm, "display_name"),
            "followers": get_cell(r, hm, "followers"),
            "bio": get_cell(r, hm, "bio"),
            "niches": get_cell(r, hm, "niches"),
        })
    return creators


def pick_top_video_for_creator(videos_rows: List[List[str]], creator_username: str) -> Optional[Dict[str, Any]]:
    """
    Select creator's best video by viral_score then engagement_metric.
    Handles creator column variations: creator_username OR creator OR username.
    """
    vhm = header_map(videos_rows)
    if "url" not in vhm:
        raise RuntimeError("videos sheet must contain 'url' column")

    creator_col = None
    for c in ["creator_username", "creator", "username", "handle"]:
        if c in vhm:
            creator_col = c
            break
    if not creator_col:
        raise RuntimeError("videos sheet must have a creator column (creator_username or creator)")

    target = normalize_username(creator_username)

    def get_num(row, colname):
        return safe_float(get_cell(row, vhm, colname)) if colname in vhm else 0.0

    candidates: List[Tuple[float, float, List[str]]] = []
    for r in videos_rows[1:]:
        cval = get_cell(r, vhm, creator_col)
        if normalize_username(cval) != target:
            continue
        url = get_cell(r, vhm, "url")
        if not url:
            continue

        viral = get_num(r, "viral_score")
        eng = get_num(r, "engagement_metric")

        if ONLY_USE_SCORED_VIDEOS:
            # scored if last_scored_at exists OR viral_score > 0
            scored = bool(get_cell(r, vhm, "last_scored_at")) or viral > 0
            if not scored:
                continue

        candidates.append((viral, eng, r))

    if not candidates:
        return None

    candidates.sort(key=lambda t: (t[0], t[1]), reverse=True)
    viral, eng, r = candidates[0]

    url = get_cell(r, vhm, "url")
    video_id = parse_video_id(url)

    return {
        "url": url,
        "video_id": video_id,
        "niche": get_cell(r, vhm, "niche"),
        "title": get_cell(r, vhm, "title"),
        "hashtags": get_cell(r, vhm, "hashtags"),
        "viral_score": str(viral),
        "engagement_metric": str(eng),
        "likes": get_cell(r, vhm, "likes"),
        "comments": get_cell(r, vhm, "comments"),
        "shares": get_cell(r, vhm, "shares"),
        "views": get_cell(r, vhm, "views"),  # may be blank
    }


def transcript_cache_get(trans_rows: List[List[str]], video_id: str) -> str:
    hm = header_map(trans_rows)
    if "video_id" not in hm or "transcript_text" not in hm:
        return ""
    for r in trans_rows[1:]:
        if get_cell(r, hm, "video_id") == video_id:
            return get_cell(r, hm, "transcript_text")
    return ""


def transcript_cache_put(trans_ws: gspread.Worksheet, video: Dict[str, Any], creator_username: str, transcript: str) -> None:
    trans_ws.append_row(
        [
            video.get("video_id", ""),
            video.get("url", ""),
            creator_username,
            "en",
            transcript,
            utcnow_iso(),
            "openai-whisper-1",
        ],
        value_input_option="RAW"
    )


def blog_already_exists(blog_rows: List[List[str]], slug: str) -> bool:
    hm = header_map(blog_rows)
    if "slug" not in hm:
        return False
    for r in blog_rows[1:]:
        if get_cell(r, hm, "slug") == slug:
            return True
    return False


# =========================
# MAIN
# =========================
def main() -> None:
    if not OPENAI_API_KEY:
        raise RuntimeError("Missing OPENAI_API_KEY. Set it with: export OPENAI_API_KEY='sk-proj-...'")

    sh = get_sheet()

    videos_ws = sh.worksheet(SHEET_VIDEOS)
    creators_ws = sh.worksheet(SHEET_CREATORS)
    blog_ws = sh.worksheet(SHEET_BLOG_POSTS)
    trans_ws = sh.worksheet(SHEET_TRANSCRIPTS)

    blog_header = [
        "id","status","created_at","published_at","slug","title","meta_description","tags",
        "niche","creator_username","creator_profile_url","followers","avg_views_est",
        "source_video_url","source_video_id","blog_image_url","blog_image_source",
        "source_video_title","source_video_views","source_video_likes","source_video_comments",
        "source_video_shares","viral_score","engagement_metric","content_markdown","notes","last_generated_at"
    ]
    trans_header = ["video_id","video_url","creator_username","language","transcript_text","transcribed_at","provider"]

    ensure_headers(blog_ws, blog_header)
    ensure_headers(trans_ws, trans_header)

    videos_rows = videos_ws.get_all_values()
    creators_rows = creators_ws.get_all_values()
    blog_rows = blog_ws.get_all_values()
    trans_rows = trans_ws.get_all_values()

    creators = load_creators(creators_rows)

    print(f"[INFO] Creators loaded from creators sheet: {len(creators)}")
    print(f"[INFO] Videos rows: {max(len(videos_rows)-1, 0)}")
    print(f"[INFO] Existing blog_posts rows: {max(len(blog_rows)-1, 0)}")
    print(f"[INFO] Existing transcripts rows: {max(len(trans_rows)-1, 0)}")
    print(f"[INFO] ONLY_USE_SCORED_VIDEOS={ONLY_USE_SCORED_VIDEOS} MAX_CREATORS_PER_RUN={MAX_CREATORS_PER_RUN}")

    created = 0

    for creator in creators:
        if created >= MAX_CREATORS_PER_RUN:
            break

        username = creator["username"]
        top_video = pick_top_video_for_creator(videos_rows, username)
        if not top_video or not top_video.get("video_id"):
            continue

        video_id = top_video["video_id"]
        slug = slugify(f"{normalize_username(username)}-{video_id}")

        if blog_already_exists(blog_rows, slug):
            continue

        # Thumbnail URL (og:image) – URL only
        blog_image_url = fetch_og_image(top_video["url"])
        blog_image_source = "video_thumbnail" if blog_image_url else ""
        if not blog_image_url and creator.get("profile_url"):
            blog_image_url = fetch_og_image(creator["profile_url"])
            blog_image_source = "fallback_profile" if blog_image_url else ""

        # Transcript cache
        transcript = transcript_cache_get(trans_rows, video_id)
        if not transcript:
            print(f"[INFO] Downloading audio for {username} video {video_id}")
            mp3_path = yt_dlp_download_audio(top_video["url"], video_id)
            if not mp3_path:
                print(f"[WARN] yt-dlp failed for {video_id}. Skipping.")
                continue

            print(f"[INFO] Transcribing {video_id} with OpenAI Whisper…")
            transcript = openai_transcribe(mp3_path)
            if not transcript:
                print(f"[WARN] Empty transcript for {video_id}. Skipping.")
                continue

            transcript_cache_put(trans_ws, top_video, username, transcript)
            trans_rows = trans_ws.get_all_values()  # refresh cache for this run

        # Build payload for blog generation
        payload = {
            "creator": {
                "username": username,
                "profile_url": creator.get("profile_url", ""),
                "display_name": creator.get("display_name", ""),
                "followers": creator.get("followers", ""),
                "bio": creator.get("bio", ""),
                "niches": creator.get("niches", ""),
            },
            "video": {
                "url": top_video.get("url", ""),
                "video_id": video_id,
                "niche": top_video.get("niche", ""),
                "title": top_video.get("title", ""),
                "hashtags": top_video.get("hashtags", ""),
                "viral_score": top_video.get("viral_score", ""),
                "engagement_metric": top_video.get("engagement_metric", ""),
                "likes": top_video.get("likes", ""),
                "comments": top_video.get("comments", ""),
                "shares": top_video.get("shares", ""),
                "views": top_video.get("views", ""),
            },
            "transcript": transcript,
        }

        print(f"[INFO] Generating blog draft for {username} / {video_id}")
        blog = openai_generate_blog_json(payload)

        niche = top_video.get("niche", "") or (creator.get("niches", "").split(",")[0].strip() if creator.get("niches") else "")
        niche = niche or "tiktok"

        title = blog.get("title") or f"Analysis of @{normalize_username(username)} in {niche}"
        meta = blog.get("meta_description") or f"A data-driven breakdown of @{normalize_username(username)}’s TikTok format in {niche}."
        tags = blog.get("tags") or f"{normalize_username(username)},{niche},tiktok,creator"
        markdown = blog.get("markdown") or ""

        # Quality guard (skip thin output)
        if len(markdown) < 800:
            print(f"[SKIP] Blog too short for {username}/{video_id} (len={len(markdown)}).")
            continue

        next_id = str(len(blog_rows))  # header is row 1
        row = [
            next_id,
            "draft",
            utcnow_iso(),
            "",
            slug,
            title,
            meta,
            tags,
            top_video.get("niche", ""),
            username,
            creator.get("profile_url", ""),
            creator.get("followers", ""),
            "",
            top_video.get("url", ""),
            video_id,
            blog_image_url,
            blog_image_source,
            top_video.get("title", ""),
            top_video.get("views", ""),
            top_video.get("likes", ""),
            top_video.get("comments", ""),
            top_video.get("shares", ""),
            top_video.get("viral_score", ""),
            top_video.get("engagement_metric", ""),
            markdown,
            "",
            utcnow_iso(),
        ]

        blog_ws.append_row([str(x) for x in row], value_input_option="RAW")
        blog_rows.append([str(x) for x in row])  # keep local list updated
        created += 1
        print(f"[OK] Draft saved: {slug}")
        time.sleep(0.5)

    print(f"\n✅ Done. Drafts created: {created}")
    if created == 0 and ONLY_USE_SCORED_VIDEOS:
        print("\n[HINT] Drafts=0 and BLOG_AGENT_SCORED_ONLY=1.")
        print("      If scoring hasn't run yet, temporarily do:")
        print('      export BLOG_AGENT_SCORED_ONLY="0"')
        print("      python creator_blog_agent.py")


if __name__ == "__main__":
    main()
PY

