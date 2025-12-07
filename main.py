from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import csv
import io
import ssl
from urllib.request import urlopen
from typing import List, Dict, Any

# ==============================
# Config
# ==============================

# Your published Google Sheets CSV URL.
# If you already have one that works, paste it here instead.
SHEET_CSV_URL = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vQ6Bxp-hOgxM3sUcxuHlex0oU1yv-m-hqyNhLYCjrYX-2wtn2xsQCbhejXrncej0u9VtneaeZCjrRQO/"
    "pub?gid=0&single=true&output=csv"
)

# Create an SSL context that does NOT verify certificates (OK for local dev)
ssl_context = ssl._create_unverified_context()

app = FastAPI(title="TrendScout Skimmer")

# Serve static files (favicon, logo, etc.)
app.mount("/static", StaticFiles(directory="static"), name="static")

# ==============================
# Helpers
# ==============================

def safe_float(x: Any) -> float:
    """
    Safely convert x to float. Returns 0.0 if conversion fails.
    """
    try:
        if x is None:
            return 0.0
        if isinstance(x, (int, float)):
            return float(x)
        s = str(x).strip().replace(",", "")
        if s == "":
            return 0.0
        return float(s)
    except Exception:
        return 0.0


def rating_to_stars(rating: float) -> str:
    """
    Convert a 0–5 rating to stars like "★★★★☆".
    """
    rating = max(0.0, min(5.0, float(rating)))
    full = int(round(rating))
    return "★" * full + "☆" * (5 - full)


def compute_agent_score(row: Dict[str, Any]) -> float:
    """
    Very simple 'Agent score' based on:
      - commission_pct
      - virality_score
      - views_7d
    You can tweak this formula later.
    """
    commission = safe_float(row.get("commission_pct", 0.0))
    virality = safe_float(row.get("virality_score", 0.0))
    views_7d = safe_float(row.get("views_7d", 0.0))

    # Normalize a bit so numbers don’t blow up
    commission_norm = commission / 5.0      # 20–30% ends up ~4–6
    virality_norm = virality / 25.0        # 75–100 → 3–4
    views_norm = views_7d ** 0.25 / 10.0   # diminishing returns

    score = commission_norm + virality_norm + views_norm
    return round(score, 2)


def load_products() -> List[Dict[str, Any]]:
    """
    Load products from the Google Sheets CSV and compute helper fields.
    """
    products: List[Dict[str, Any]] = []

    try:
        with urlopen(SHEET_CSV_URL, context=ssl_context) as resp:
            data = resp.read().decode("utf-8")
    except Exception as e:
        print("Error loading CSV:", e)
        return products

    reader = csv.DictReader(io.StringIO(data))
    for row in reader:
        # Clean up core fields
        row["name"] = (row.get("name") or "").strip()
        row["category"] = (row.get("category") or "").strip()
        row["price"] = (row.get("price") or "").strip()
        row["commission_pct"] = (row.get("commission_pct") or "").strip()
        row["virality_score"] = (row.get("virality_score") or "").strip()
        row["views_7d"] = (row.get("views_7d") or "").strip()

        # Rating numeric + stars
        rating_val = safe_float(row.get("rating", 0.0))
        row["rating_value"] = rating_val
        row["rating_display"] = f"{rating_val:.1f}" if rating_val > 0 else "—"
        row["rating_stars"] = rating_to_stars(rating_val) if rating_val > 0 else "☆☆☆☆☆"

        # Agent score
        row["agent_score"] = compute_agent_score(row)

        products.append(row)

    return products


# ==============================
# HTML Template
# ==============================

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8" />
    <title>TrendScout Skimmer</title>
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <link rel="icon" type="image/png" href="/static/favicon.png" />

    <style>
        :root {{
            --bg: #030712;
            --bg-soft: #020617;
            --card: #020617;
            --accent: #38bdf8;
            --accent-soft: rgba(56,189,248,0.15);
            --accent-strong: #0ea5e9;
            --text-main: #e5e7eb;
            --text-soft: #9ca3af;
            --border-soft: rgba(148,163,184,0.35);
            --header: #020617;
        }}

        * {{
            box-sizing: border-box;
        }}

        body {{
            margin: 0;
            font-family: system-ui, -apple-system, BlinkMacSystemFont, "SF Pro Text", sans-serif;
            background: radial-gradient(circle at top left, #0f172a 0, #020617 45%, #000 100%);
            color: var(--text-main);
        }}

        .page-wrap {{
            min-height: 100vh;
            padding: 24px 16px 40px;
            display: flex;
            justify-content: center;
        }}

        .shell {{
            width: 100%;
            max-width: 1200px;
        }}

        .badge-row {{
            display: flex;
            gap: 10px;
            align-items: center;
            margin-bottom: 12px;
            flex-wrap: wrap;
        }}

        .badge {{
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.12em;
            border-radius: 999px;
            padding: 4px 10px;
            border: 1px solid rgba(148,163,184,0.5);
            color: var(--text-soft);
            display: inline-flex;
            align-items: center;
            gap: 6px;
        }}

        .badge-dot {{
            width: 8px;
            height: 8px;
            border-radius: 999px;
            background: #22c55e;
            box-shadow: 0 0 0 6px rgba(34,197,94,0.25);
        }}

        .badge-pill {{
            background: rgba(15,23,42,0.9);
        }}

        .hero {{
            margin-bottom: 18px;
            padding-bottom: 10px;
            border-bottom: 1px solid rgba(15,23,42,0.9);
        }}

        .hero-main {{
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 4px;
        }}

        .logo-mark {{
            width: 32px;
            height: 32px;
            border-radius: 999px;
            background: radial-gradient(circle at 30% 20%, #e0f2fe 0, #0ea5e9 32%, #0369a1 75%, #020617 100%);
            display: flex;
            align-items: center;
            justify-content: center;
            box-shadow:
                0 0 0 1px rgba(15,23,42,0.9),
                0 10px 35px rgba(56,189,248,0.45);
        }}

        .logo-glyph {{
            font-size: 17px;
            font-weight: 700;
            color: #0b1120;
        }}

        .hero-title {{
            font-size: 22px;
            font-weight: 650;
            letter-spacing: 0.02em;
        }}

        .hero-sub {{
            font-size: 13px;
            color: var(--text-soft);
        }}

        .hero-sub span.sparkle {{
            color: var(--accent);
        }}

        .controls-row {{
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            align-items: center;
            margin-bottom: 16px;
        }}

        .search-wrap {{
            flex: 1 1 220px;
            min-width: 0;
            position: relative;
        }}

        .search-input {{
            width: 100%;
            background: radial-gradient(circle at top left, #020617 0, #020617 40%, #020617 100%);
            border-radius: 999px;
            border: 1px solid rgba(148,163,184,0.35);
            color: var(--text-main);
            padding: 8px 14px 8px 32px;
            font-size: 13px;
            outline: none;
            transition: border-color 0.14s ease, box-shadow 0.15s ease, background 0.18s ease;
        }}

        .search-input::placeholder {{
            color: rgba(148,163,184,0.7);
        }}

        .search-input:focus {{
            border-color: var(--accent-strong);
            box-shadow: 0 0 0 1px rgba(56,189,248,0.4), 0 0 0 12px rgba(8,47,73,0.9);
        }}

        .search-icon {{
            position: absolute;
            left: 10px;
            top: 50%;
            transform: translateY(-50%);
            font-size: 13px;
            opacity: 0.8;
        }}

        .control-chips {{
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
        }}

        .chip {{
            font-size: 11px;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: var(--text-soft);
            border-radius: 999px;
            padding: 6px 10px;
            border: 1px solid rgba(148,163,184,0.4);
            background: rgba(15,23,42,0.85);
            display: inline-flex;
            gap: 6px;
            align-items: center;
        }}

        .chip.primary {{
            border-color: rgba(56,189,248,0.9);
            background: linear-gradient(135deg, rgba(56,189,248,0.22), rgba(8,47,73,0.95));
            color: #e0f2fe;
        }}

        .chip-dot {{
            width: 7px;
            height: 7px;
            border-radius: 999px;
            background: var(--accent-strong);
        }}

        .table-shell {{
            border-radius: 16px;
            border: 1px solid rgba(15,23,42,0.9);
            background: radial-gradient(circle at top, #020617 0, #020617 45%, #020617 100%);
            box-shadow:
                0 18px 45px rgba(15,23,42,0.75),
                0 0 0 1px rgba(15,23,42,1);
            overflow: hidden;
        }}

        .table-scroll {{
            max-height: calc(100vh - 200px);
            overflow: auto;
        }}

        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
        }}

        thead {{
            background: rgba(15,23,42,0.98);
            position: sticky;
            top: 0;
            z-index: 5;
        }}

        th, td {{
            padding: 9px 12px;
            white-space: nowrap;
        }}

        th {{
            text-align: left;
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.11em;
            color: rgba(148,163,184,0.9);
            border-bottom: 1px solid rgba(31,41,55,0.9);
            background: radial-gradient(circle at top, #020617 0, #020617 45%, #020617 100%);
            position: relative;
            cursor: pointer;
        }}

        th.sortable:hover {{
            color: var(--accent);
        }}

        th .sort-indicator {{
            opacity: 0.2;
            font-size: 11px;
            margin-left: 4px;
        }}

        th.active-sort {{
            color: var(--accent-strong);
        }}

        th.active-sort .sort-indicator {{
            opacity: 0.9;
        }}

        tbody tr:nth-child(even) {{
            background: rgba(15,23,42,0.6);
        }}

        tbody tr:nth-child(odd) {{
            background: rgba(15,23,42,0.3);
        }}

        tbody tr:hover {{
            background: rgba(15,23,42,0.95);
        }}

        td.name-cell {{
            font-weight: 500;
        }}

        td.category-cell {{
            color: var(--text-soft);
        }}

        td.numeric-cell {{
            text-align: right;
            font-variant-numeric: tabular-nums;
        }}

        .pill-link {{
            font-size: 11px;
            padding: 4px 10px;
            border-radius: 999px;
            border: 1px solid rgba(148,163,184,0.5);
            text-decoration: none;
            color: #e5e7eb;
            display: inline-flex;
            gap: 4px;
            align-items: center;
            background: rgba(15,23,42,0.85);
        }}

        .pill-link:hover {{
            border-color: var(--accent);
            color: #bae6fd;
            background: rgba(8,47,73,0.9);
        }}

        .pill-link span.icon {{
            font-size: 10px;
            opacity: 0.8;
        }}

        .rating-wrap {{
            display: flex;
            flex-direction: column;
            gap: 2px;
            align-items: flex-end;
        }}

        .rating-stars {{
            font-size: 11px;
            letter-spacing: 1px;
            color: #fbbf24;
        }}

        .rating-number {{
            font-size: 11px;
            color: var(--text-soft);
        }}

        .agent-score {{
            font-weight: 500;
            color: #a5b4fc;
        }}

        .agent-chip {{
            font-size: 10px;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: #a5b4fc;
            border-radius: 999px;
            padding: 3px 7px;
            border: 1px solid rgba(129,140,248,0.4);
            background: rgba(30,64,175,0.25);
            margin-left: 4px;
        }}

        @media (max-width: 768px) {{
            .hero-main {{
                align-items: flex-start;
            }}
            .hero-title {{
                font-size: 19px;
            }}
            th, td {{
                padding: 7px 8px;
            }}
        }}
    </style>
</head>
<body>
<div class="page-wrap">
    <div class="shell">

        <div class="badge-row">
            <div class="badge badge-pill">
                <span class="badge-dot"></span>
                Live TikTok product radar
            </div>
            <div class="badge">
                Agent-Scored by TrendScout
            </div>
        </div>

        <div class="hero">
            <div class="hero-main">
                <div class="logo-mark">
                    <div class="logo-glyph">TS</div>
                </div>
                <div>
                    <div class="hero-title">TrendScout Skimmer</div>
                    <div class="hero-sub">
                        Tracks viral TikTok products from your sheet so you can ride the wave before it crashes.
                        <span class="sparkle">Refresh page after updating Google Sheets.</span>
                    </div>
                </div>
            </div>
        </div>

        <div class="controls-row">
            <div class="search-wrap">
                <span class="search-icon">🔍</span>
                <input id="searchBox" class="search-input"
                    placeholder="Search by name or category…" />
            </div>
            <div class="control-chips">
                <div class="chip primary">
                    <span class="chip-dot"></span>
                    Sort by payout or virality — click any header
                </div>
                <div class="chip">
                    Agent score blends commission, virality & 7-day views
                </div>
            </div>
        </div>

        <div class="table-shell">
            <div class="table-scroll">
                <table id="productTable">
                    <thead>
                        <tr>
                            <th class="sortable" data-col="0" data-type="text">Name <span class="sort-indicator">▲▼</span></th>
                            <th class="sortable" data-col="1" data-type="text">Category <span class="sort-indicator">▲▼</span></th>
                            <th class="sortable" data-col="2" data-type="numeric">Price <span class="sort-indicator">▲▼</span></th>
                            <th class="sortable" data-col="3" data-type="numeric">Commission % <span class="sort-indicator">▲▼</span></th>
                            <th class="sortable" data-col="8" data-type="numeric">Agent score <span class="sort-indicator">▲▼</span></th>
                            <th class="sortable" data-col="4" data-type="numeric">Virality <span class="sort-indicator">▲▼</span></th>
                            <th class="sortable" data-col="5" data-type="numeric">7-day views <span class="sort-indicator">▲▼</span></th>
                            <th class="sortable" data-col="6" data-type="numeric">Rating <span class="sort-indicator">▲▼</span></th>
                            <th data-col="7">Links</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows_html}
                    </tbody>
                </table>
            </div>
        </div>

    </div>
</div>

<script>
(function() {{
    const table = document.getElementById("productTable");
    const tbody = table.querySelector("tbody");
    const headers = table.querySelectorAll("th.sortable");
    let currentSortCol = null;
    let currentSortDir = 1; // 1 = asc, -1 = desc

    function sortTable(colIndex, type) {{
        const rows = Array.from(tbody.querySelectorAll("tr"));
        rows.sort((a, b) => {{
            const aCell = a.children[colIndex].getAttribute("data-sort") || a.children[colIndex].innerText;
            const bCell = b.children[colIndex].getAttribute("data-sort") || b.children[colIndex].innerText;

            if (type === "numeric") {{
                const aVal = parseFloat(aCell.replace(/,/g, "")) || 0;
                const bVal = parseFloat(bCell.replace(/,/g, "")) || 0;
                return (aVal - bVal) * currentSortDir;
            }} else {{
                return aCell.localeCompare(bCell) * currentSortDir;
            }}
        }});

        rows.forEach(r => tbody.appendChild(r));
    }}

    headers.forEach(h => {{
        h.addEventListener("click", () => {{
            const colIndex = parseInt(h.getAttribute("data-col"));
            const type = h.getAttribute("data-type") || "text";

            if (currentSortCol === colIndex) {{
                currentSortDir = -currentSortDir;
            }} else {{
                currentSortCol = colIndex;
                currentSortDir = 1;
            }}

            headers.forEach(x => x.classList.remove("active-sort"));
            h.classList.add("active-sort");

            sortTable(colIndex, type);
        }});
    }});

    const searchBox = document.getElementById("searchBox");
    searchBox.addEventListener("input", () => {{
        const term = searchBox.value.toLowerCase();
        const rows = Array.from(tbody.querySelectorAll("tr"));
        rows.forEach(row => {{
            const nameText = row.querySelector(".name-cell").innerText.toLowerCase();
            const catText = row.querySelector(".category-cell").innerText.toLowerCase();
            if (nameText.includes(term) || catText.includes(term)) {{
                row.style.display = "";
            }} else {{
                row.style.display = "none";
            }}
        }});
    }});
}})();
</script>

</body>
</html>
"""


# ==============================
# Routes
# ==============================

@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    products = load_products()

    def format_price(val: str) -> str:
        v = safe_float(val)
        if v == 0:
            return "-"
        return f"${v:,.2f}"

    def fmt_int(val: str) -> str:
        v = safe_float(val)
        if v == 0:
            return "0"
        return f"{int(v):,}"

    rows = []
    for p in products:
        name = p.get("name", "")
        category = p.get("category", "")

        price_display = format_price(p.get("price", ""))
        commission_display = f"{safe_float(p.get('commission_pct', 0.0)):.0f}%"
        virality_display = f"{safe_float(p.get('virality_score', 0.0)):.1f}"
        views_7d_display = fmt_int(p.get("views_7d", "0"))

        rating_display = p.get("rating_display", "—")
        rating_stars = p.get("rating_stars", "☆☆☆☆☆")

        agent_score = p.get("agent_score", 0.0)

        tiktok_url = (p.get("tiktok_video_url") or "").strip()
        shop_url = (p.get("tiktok_shop_url") or "").strip()

        tiktok_link = (
            f'<a class="pill-link" href="{tiktok_url}" target="_blank" rel="noopener">'
            f'<span class="icon">▶</span>TikTok</a>'
            if tiktok_url else "—"
        )
        shop_link = (
            f'<a class="pill-link" href="{shop_url}" target="_blank" rel="noopener">'
            f'<span class="icon">🛒</span>Shop</a>'
            if shop_url else "—"
        )

        links_cell = f"{tiktok_link}&nbsp;&nbsp;{shop_link}"

        row_html = f"""
        <tr>
            <td class="name-cell" data-sort="{name}">{name}</td>
            <td class="category-cell" data-sort="{category}">{category}</td>
            <td class="numeric-cell" data-sort="{safe_float(p.get('price',0.0))}">{price_display}</td>
            <td class="numeric-cell" data-sort="{safe_float(p.get('commission_pct',0.0))}">{commission_display}</td>
            <td class="numeric-cell" data-sort="{agent_score}">
                <span class="agent-score">{agent_score:.2f}</span>
                <span class="agent-chip">Agent</span>
            </td>
            <td class="numeric-cell" data-sort="{safe_float(p.get('virality_score',0.0))}">{virality_display}</td>
            <td class="numeric-cell" data-sort="{safe_float(p.get('views_7d',0.0))}">{views_7d_display}</td>
            <td class="numeric-cell" data-sort="{safe_float(p.get('rating_value',0.0))}">
                <div class="rating-wrap">
                    <div class="rating-stars">{rating_stars}</div>
                    <div class="rating-number">{rating_display}</div>
                </div>
            </td>
            <td data-sort="0">{links_cell}</td>
        </tr>
        """
        rows.append(row_html)

    html = HTML_TEMPLATE.format(rows_html="\n".join(rows))
    return HTMLResponse(content=html)


@app.get("/api/products", response_class=JSONResponse)
def api_products() -> JSONResponse:
    """
    Simple JSON endpoint if you ever want to hit the data from another tool.
    """
    return JSONResponse(load_products())

