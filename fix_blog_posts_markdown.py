import os, json
import gspread
from dotenv import load_dotenv

load_dotenv(dotenv_path=".env", override=True)

SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
if not SHEET_ID:
    raise RuntimeError("Missing GOOGLE_SHEET_ID")

gc = gspread.service_account(filename="service_account.json")
sh = gc.open_by_key(SHEET_ID)
ws = sh.worksheet("blog_posts")

rows = ws.get_all_values()
if len(rows) < 2:
    print("No rows.")
    raise SystemExit(0)

header = [h.strip() for h in rows[0]]
def idx(name):
    try: return header.index(name)
    except ValueError: return None

i_md = idx("content_markdown")
i_title = idx("title")
i_meta = idx("meta_description")
i_tags = idx("tags")

if i_md is None:
    raise RuntimeError("blog_posts missing content_markdown column")

fixed = 0

for r_i in range(2, len(rows)+1):  # 1-based in Sheets; start after header
    row = rows[r_i-1]
    md = row[i_md] if i_md < len(row) else ""
    s = (md or "").strip()

    # Detect JSON blob
    candidate = s
    if candidate.startswith("```json"):
        candidate = candidate.replace("```json", "").replace("```", "").strip()

    if candidate.startswith("{") and '"markdown"' in candidate:
        try:
            data = json.loads(candidate)
            new_md = (data.get("markdown") or "").strip()
            new_title = (data.get("title") or "").strip()
            new_meta = (data.get("meta_description") or "").strip()
            new_tags = (data.get("tags") or "").strip()

            if new_md and new_md != s:
                # update markdown
                ws.update(range_name=f"{gspread.utils.rowcol_to_a1(r_i, i_md+1)}",
                          values=[[new_md]])
                # optionally update fields if present
                if i_title is not None and new_title:
                    ws.update(range_name=f"{gspread.utils.rowcol_to_a1(r_i, i_title+1)}",
                              values=[[new_title]])
                if i_meta is not None and new_meta:
                    ws.update(range_name=f"{gspread.utils.rowcol_to_a1(r_i, i_meta+1)}",
                              values=[[new_meta]])
                if i_tags is not None and new_tags:
                    ws.update(range_name=f"{gspread.utils.rowcol_to_a1(r_i, i_tags+1)}",
                              values=[[new_tags]])

                fixed += 1
                print(f"[OK] Fixed row {r_i}")
        except Exception:
            pass

print(f"\nDone. Rows fixed: {fixed}")

