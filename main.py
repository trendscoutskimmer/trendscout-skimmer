import os
import json
import re
from datetime import datetime
from typing import Optional, List, Dict, Any

import gspread
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from openai import OpenAI

# -------------------------------------------------
# Setup
# -------------------------------------------------
load_dotenv()

BASE_DIR = os.path.dirname(__file__)
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
UI_FILE = os.path.join(BASE_DIR, "ui_slim.html")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# Google Sheets (blog pages)
SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", os.path.join(BASE_DIR, "service_account.json"))
DEFAULT_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "1XNkTaG02oj76pzxt_TC0-o2ug7zTbpSJl3FK5k2jpXQ")
BLOG_POSTS_SHEET = os.getenv("BLOG_POSTS_SHEET", "blog_posts")

templates = Jinja2Templates(directory=TEMPLATES_DIR)

app = FastAPI(title="Viral Auditor")

# -------------------------------------------------
# Models
# -------------------------------------------------
class AuditRequest(BaseModel):
    url: Optional[str] = None
    title: str
    description: Optional[str] = None
    transcript: Optional[str] = None
    thumbnail_url: Optional[str] = None


class AuditResponse(BaseModel):
    score: int
    verdict: str
    notes: str
    hook_score: Optional[int] = None
    pacing_score: Optional[int] = None
    retention_score: Optional[int] = None
    niche_fit_score: Optional[int] = None
    hashtags: Optional[List[str]] = None
    error: Optional[str] = None


# -------------------------------------------------
# Small helpers
# -------------------------------------------------
def clamp_int(value: float, low: int = 0, high: int = 100) -> int:
    try:
        return max(low, min(high, int(round(float(value)))))
    except Exception:
        return low


def _safe_json_loads(s: str) -> Dict[str, Any]:
    try:
        return json.loads(s)
    except Exception:
        return {}


def _normalize_header(header_row: List[str]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for i, h in enumerate(header_row or []):
        key = (h or "").strip().lower()
        if key:
            out[key] = i
    return out


def _pick(row: List[str], hm: Dict[str, int], key: str) -> str:
    i = hm.get(key)
    if i is None or i >= len(row):
        return ""
    return (row[i] or "").strip()


_gs_client = None
_gs_sheet = None

def get_sheet():
    """Cached gspread Spreadsheet."""
    global _gs_client, _gs_sheet
    if _gs_sheet is not None:
        return _gs_sheet
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        raise RuntimeError(f"Missing service account file: {SERVICE_ACCOUNT_FILE}")
    _gs_client = gspread.service_account(filename=SERVICE_ACCOUNT_FILE)
    _gs_sheet = _gs_client.open_by_key(DEFAULT_SHEET_ID)
    return _gs_sheet


def parse_dt(s: str) -> Optional[datetime]:
    s = (s or "").strip()
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def read_blog_posts(limit: int = 50) -> List[Dict[str, Any]]:
    sh = get_sheet()
    ws = sh.worksheet(BLOG_POSTS_SHEET)
    rows = ws.get_all_values()
    if not rows:
        return []
    header = rows[0]
    hm = _normalize_header(header)
    posts = []
    for r in rows[1:]:
        slug = _pick(r, hm, "slug")
        if not slug:
            continue
        posts.append({
            "id": _pick(r, hm, "id"),
            "status": _pick(r, hm, "status"),
            "created_at": _pick(r, hm, "created_at"),
            "published_at": _pick(r, hm, "published_at"),
            "slug": slug,
            "title": _pick(r, hm, "title"),
            "meta_description": _pick(r, hm, "meta_description"),
            "tags": _pick(r, hm, "tags"),
            "niche": _pick(r, hm, "niche"),
            "creator_username": _pick(r, hm, "creator_username"),
            "creator_profile_url": _pick(r, hm, "creator_profile_url"),
            "source_video_url": _pick(r, hm, "source_video_url"),
            "source_video_id": _pick(r, hm, "source_video_id"),
            "blog_image_url": _pick(r, hm, "blog_image_url"),
            "blog_image_source": _pick(r, hm, "blog_image_source"),
            "viral_score": _pick(r, hm, "viral_score"),
            "engagement_metric": _pick(r, hm, "engagement_metric"),
            "content_markdown": _pick(r, hm, "content_markdown"),
        })
    # newest first (created_at if possible)
    posts.sort(key=lambda p: (parse_dt(p.get("created_at") or "") or datetime.min), reverse=True)
    return posts[:limit]


def get_blog_post_by_slug(slug: str) -> Optional[Dict[str, Any]]:
    slug = (slug or "").strip()
    if not slug:
        return None
    posts = read_blog_posts(limit=5000)
    for p in posts:
        if p.get("slug") == slug:
            return p
    return None


# -------------------------------------------------
# Core AI virality audit
# -------------------------------------------------
def run_openai_audit(req: AuditRequest) -> AuditResponse:
    if client is None:
        raise RuntimeError("OPENAI_API_KEY not set")

    user_context = {
        "url": req.url or "",
        "title": req.title,
        "description": req.description or "",
        "transcript": req.transcript or "",
        "thumbnail_url": req.thumbnail_url or "",
    }

    system = (
        "You are a brutally honest short-form growth analyst. "
        "You score virality (0-100) and give concrete, non-generic fixes."
    )

    prompt = f"""
Score this short-form video concept for virality from 0-100.

Return VALID JSON only with these keys:
score (number 0-100),
verdict (short string),
notes (string, concise but actionable),
hook_score (0-100),
pacing_score (0-100),
retention_score (0-100),
niche_fit_score (0-100),
hashtags (array of 6-12 strings, include #).

Context:
{json.dumps(user_context, ensure_ascii=False)}
"""

    resp = client.responses.create(
        model=os.getenv("AUDIT_MODEL", "gpt-4.1-mini"),
        input=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
    )
    text = (getattr(resp, "output_text", "") or "").strip()
    data = _safe_json_loads(text)

    if not data:
        raise RuntimeError(f"Model did not return JSON. Output: {text[:300]}")

    return AuditResponse(
        score=clamp_int(data.get("score", 0)),
        verdict=str(data.get("verdict", "—")).strip()[:120],
        notes=str(data.get("notes", "")).strip(),
        hook_score=clamp_int(data.get("hook_score", 0)) if data.get("hook_score") is not None else None,
        pacing_score=clamp_int(data.get("pacing_score", 0)) if data.get("pacing_score") is not None else None,
        retention_score=clamp_int(data.get("retention_score", 0)) if data.get("retention_score") is not None else None,
        niche_fit_score=clamp_int(data.get("niche_fit_score", 0)) if data.get("niche_fit_score") is not None else None,
        hashtags=data.get("hashtags") if isinstance(data.get("hashtags"), list) else None,
    )


def fallback_audit(req: AuditRequest, err: str) -> AuditResponse:
    # Minimal deterministic fallback so UI never breaks.
    title = (req.title or "").strip()
    transcript = (req.transcript or "").strip()
    length_hint = len(title) + len(transcript)

    score = 40
    if len(title) >= 20:
        score += 5
    if transcript:
        score += 5
    if "how" in title.lower() or "watch" in title.lower():
        score += 4
    if length_hint > 400:
        score += 4

    score = clamp_int(score, 0, 85)

    return AuditResponse(
        score=score,
        verdict="Fallback audit (OpenAI unavailable)",
        notes=(
            "OpenAI audit failed, so this is a basic fallback. "
            "Add a clearer outcome in the first 1–2 seconds, tighten pacing, "
            "and make the payoff obvious."
        ),
        hook_score=min(80, score),
        pacing_score=min(80, max(35, score - 5)),
        retention_score=min(80, max(35, score - 8)),
        niche_fit_score=min(80, max(35, score - 10)),
        hashtags=["#tiktok", "#reels", "#shorts", "#contentcreator", "#viral", "#howto"],
        error=err[:300],
    )


# -------------------------------------------------
# Routes
# -------------------------------------------------
@app.get("/")
def root():
    return RedirectResponse(url="/ui")


@app.get("/ui", response_class=FileResponse)
def serve_ui():
    if not os.path.exists(UI_FILE):
        raise HTTPException(status_code=500, detail=f"Missing UI file: {UI_FILE}")
    return FileResponse(UI_FILE)


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/audit", response_model=AuditResponse)
def audit(req: AuditRequest):
    try:
        return run_openai_audit(req)
    except Exception as e:
        return fallback_audit(req, str(e))


# ---- Blog pages ----
@app.get("/blog")
def blog_index(request: Request):
    posts = read_blog_posts(limit=50)
    return templates.TemplateResponse("blog_index.html", {"request": request, "posts": posts})


@app.get("/blog/{slug}")
def blog_post(request: Request, slug: str):
    post = get_blog_post_by_slug(slug)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    return templates.TemplateResponse("blog_post.html", {"request": request, "post": post})


@app.get("/api/blog_posts")
def api_blog_posts(limit: int = 50):
    posts = read_blog_posts(limit=min(max(limit, 1), 200))
    # send a smaller payload (no markdown) by default
    out = []
    for p in posts:
        q = dict(p)
        q.pop("content_markdown", None)
        out.append(q)
    return JSONResponse(content={"posts": out})


# ---- Run existing blog agent ----
@app.post("/api/blog/run")
async def run_blog_agent():
    """Runs creator_blog_agent.py exactly as it works now (sheets → visit → transcribe → write → blog_posts)."""
    try:
        import creator_blog_agent  # local file
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not import creator_blog_agent.py: {e}")

    def _run():
        # This calls the script's main() function, preserving behavior.
        creator_blog_agent.main()
        return {"ok": True, "message": "Blog agent finished."}

    try:
        result = await run_in_threadpool(_run)
        return JSONResponse(content=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Blog agent failed: {e}")
