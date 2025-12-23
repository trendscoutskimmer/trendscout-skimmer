from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Tuple


@dataclass
class UserMetrics:
    likes: int
    comments: int
    shares: int
    favorites: int


def safe_int(v) -> int:
    try:
        if v is None:
            return 0
        s = str(v).replace(",", "").strip()
        if not s:
            return 0
        return int(float(s))
    except Exception:
        return 0


def engagement_metric(m: UserMetrics) -> float:
    """
    Simple composite engagement metric used across your project.
    (You can evolve this later.)
    """
    # Shares weighted highest, then comments, then favorites
    return (3.0 * m.shares) + (2.0 * m.comments) + (1.0 * m.favorites) + (0.25 * m.likes)


def score_from_niche_average(metric: float, niche_avg: float) -> float:
    """
    Convert metric vs niche_avg into a normalized 0–100 score.
    """
    if niche_avg <= 0:
        return 0.0
    ratio = metric / niche_avg

    # Smooth-ish mapping
    if ratio >= 3.0:
        return 97.0
    if ratio >= 2.0:
        return 92.0
    if ratio >= 1.5:
        return 86.0
    if ratio >= 1.2:
        return 78.0
    if ratio >= 1.0:
        return 70.0
    if ratio >= 0.8:
        return 62.0
    if ratio >= 0.6:
        return 54.0
    if ratio >= 0.4:
        return 45.0
    return 35.0


def subscores(metric: float, niche_avg: float, hashtag_match: float, niche_heat: float) -> Dict[str, float]:
    """
    Split into your UI’s subscores. Keep these stable for the front-end.
    """
    eng = score_from_niche_average(metric, niche_avg)
    # hashtag_match 0..1 => 0..100
    htag = max(0.0, min(100.0, hashtag_match * 100.0))
    nh = max(0.0, min(100.0, niche_heat * 100.0))
    return {
        "engagement_score": round(eng / 100.0, 2),
        "hashtag_score": round(htag / 100.0, 2),
        "niche_heat_score": round(nh / 100.0, 2),
    }

