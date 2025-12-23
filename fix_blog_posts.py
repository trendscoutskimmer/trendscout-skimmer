# fix_blog_posts.py
# One-time repair tool:
# - If blog_posts.content_markdown contains JSON (or ```json), extract markdown/title/meta/tags
# - Write them into the correct columns
# - Ensure slug exists
# - Optionally create a "view_url" column for easy clicking

import os
import json
import re
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple

import gspread
from dotenv import load_dotenv


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_slug(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"^@", "", s)
    s = re.sub(r"[^a-z0-9\-]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or "post"


def parse_jsonish(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    t = text.strip()

    # remove ```json fences if present
    if t.startswith("```"):
        t = re.sub(r"^```json\s*", "", t, flags=re.IGNORECASE)
        t = re.sub(r"^```\s*", "", t, flags=re.IGNORECASE)
        t = re.sub(r"\s*```$", "", t).strip()

    # Sometimes pasted JSON is wrapped in quotes with doubled quotes
    # e.g. ""title"": ""X""
    if '""title""' in t or '""markdown""' in t:
        t = t.replace('""', '"')

    # Must look like JSON object
    if not (t.startswith("{") and t.endswith("}")):
        return None

    try:
        return json.loads(t)
    except Exception:
        return None


def tags_to_string(tags_val: Any) -> str:
    if tags_val is None:
        return ""
    if isinstance(tags_val, list):
        # flatten and strip
        return ",".join([str(x).strip().lstrip("#") for x in tags_val if str(x).strip()])
    # already string
    return str(tags_val).strip()


def main():
    load_dotenv(dotenv_path=".env", override=True)

    sheet_id = os.getenv("GOOGLE_SHEET_ID") or os.getenv("SHEET_ID")
    if not sheet_id:
        raise RuntimeError("Missing GOOGLE_SHEET_ID in .env")

    gc = gspread.service_account(filename="service_account.json")
    sh = gc.open_by_key(sheet_id)
    ws = sh.worksheet("blog_posts")

    rows = ws.get_all_values()
    if not rows:
        print("[INFO] blog_posts is empty")
        return

    header = rows[0]
    idx = {h: i for i, h in enumerate(header)}

    required_cols = [
        "id", "slug", "title", "meta_description", "tags",
        "creator_username", "source_video_id",
        "content_markdown", "last_generated_at",
    ]
    missing = [c for c in required_cols if c not in idx]
    if missing:
        print("[WARN] Missing columns:", missing)
        print("[WARN] I will still try to fix whatever exists.")
    else:
        print("[OK] Columns look good.")

    # Optional: add view_url column if not present
    if "view_url" not in idx:
        header.append("view_url")
        ws.update("A1", [header])
        idx = {h: i for i, h in enumerate(header)}
        print("[OK] Added view_url column.")

    fixed = 0
    created_slug = 0

    # Build batch updates
    updates = []  # (row_number, row_values)

    for r_i, r in enumerate(rows[1:], start=2):  # sheet row numbers start at 1
        # pad row
        if len(r) < len(header):
            r = r + [""] * (len(header) - len(r))

        content = r[idx.get("content_markdown", -1)] if "content_markdown" in idx else ""
        parsed = parse_jsonish(content)

        # If content_markdown is JSON-ish, extract markdown and friends
        did_fix_this = False
        if parsed and isinstance(parsed, dict):
            md = (parsed.get("markdown") or "").strip()
            ttl = (parsed.get("title") or "").strip()
            meta = (parsed.get("meta_description") or "").strip()
            tags = tags_to_string(parsed.get("tags"))

            # Only overwrite if target fields are blank or content_markdown is clearly json
            if md:
                if "content_markdown" in idx:
                    r[idx["content_markdown"]] = md
                did_fix_this = True

            if ttl and "title" in idx and not (r[idx["title"]] or "").strip():
                r[idx["title"]] = ttl
                did_fix_this = True

            if meta and "meta_description" in idx and not (r[idx["meta_description"]] or "").strip():
                r[idx["meta_description"]] = meta
                did_fix_this = True

            if tags and "tags" in idx and not (r[idx["tags"]] or "").strip():
                r[idx["tags"]] = tags
                did_fix_this = True

        # Ensure slug exists (even if not JSON)
        slug = (r[idx.get("slug", -1)] if "slug" in idx else "").strip()
        if "slug" in idx and not slug:
            cu = (r[idx.get("creator_username", -1)] if "creator_username" in idx else "").strip()
            vid = (r[idx.get("source_video_id", -1)] if "source_video_id" in idx else "").strip()
            base = normalize_slug(cu) if cu else "creator"
            suffix = vid if vid else str(r_i)
            r[idx["slug"]] = f"{base}-{suffix}"
            created_slug += 1
            did_fix_this = True

        # Always maintain a clickable view_url
        if "view_url" in idx:
            slug2 = (r[idx["slug"]] if "slug" in idx else "").strip()
            if slug2:
                r[idx["view_url"]] = f"/blog/{slug2}"

        if did_fix_this:
            if "last_generated_at" in idx:
                r[idx["last_generated_at"]] = now_iso()
            updates.append((r_i, r))
            fixed += 1

    print(f"[INFO] Rows to update: {len(updates)} (fixed={fixed}, new_slugs={created_slug})")

    # Apply updates in chunks
    CHUNK = 50
    for i in range(0, len(updates), CHUNK):
        chunk = updates[i:i+CHUNK]
        # Build range update
        start_row = chunk[0][0]
        end_row = chunk[-1][0]
        rng = f"A{start_row}:{gspread.utils.rowcol_to_a1(end_row, len(header)).split(str(end_row))[-1]}{end_row}"

        values = [row for _, row in chunk]
        # Use named args to avoid deprecation warning
        ws.update(range_name=rng, values=values, value_input_option="RAW")
        print(f"[OK] Updated rows {start_row}-{end_row}")

    print("[DONE] blog_posts repaired ✅")


if __name__ == "__main__":
    main()

