from __future__ import annotations

import re
from collections import defaultdict
from typing import Iterable


POLISH_HASHTAGS = {
    "polska", "poland", "polskitiktok", "warszawa", "krakow", "wroclaw",
    "poznan", "gdansk", "szczecin", "lodz", "katowice", "polak", "polka",
    "polski", "polskie", "polsku"
}

POLISH_WORDS = {
    "jest", "nie", "tak", "dla", "jak", "mam", "moja", "moje", "mój",
    "czy", "się", "sie", "ale", "też", "tez", "tylko", "dzisiaj", "dziś",
    "juz", "już", "będzie", "bedzie", "było", "bylo", "tego", "kiedy",
    "kto", "co", "od", "przez", "polska", "polski", "polskie", "warszawa",
    "kraków", "wrocław", "poznań", "gdańsk", "szczecin"
}

TOKEN_RE = re.compile(r"[a-ząćęłńóśźż0-9]+", re.IGNORECASE)
POLISH_DIACRITICS_RE = re.compile(r"[ąćęłńóśźż]", re.IGNORECASE)


# Patterns use roots/phrases intentionally, but short tokens such as "ai" are
# matched as whole tokens only. This fixes the old bug where "ai" could match
# inside unrelated words and push accounts into Tech.
CATEGORY_PATTERNS = {
    "Entertainment": {
        "roots": [
            "humor", "komed", "śmieszn", "smieszn", "żart", "zart", "meme",
            "skecz", "absurd", "rozrywk", "prank", "pov", "showbiz",
        ],
        "tokens": ["funny"],
        "phrases": [],
    },
    "Lifestyle": {
        "roots": [
            "lifestyle", "rodzin", "dzieci", "codzien", "życie", "zycie",
            "mama", "tata",
        ],
        "tokens": ["daily", "vlog", "life"],
        "phrases": ["dzień z życia", "dzien z zycia"],
    },
    "Beauty": {
        "roots": ["beauty", "makija", "kosmet", "skincare", "urod", "paznok"],
        "tokens": ["makeup"],
        "phrases": [],
    },
    "Fashion": {
        "roots": ["fashion", "moda", "styliz", "ubran", "odzież", "odziez"],
        "tokens": ["outfit", "style"],
        "phrases": [],
    },
    "Gaming": {
        "roots": ["gaming", "gracz", "esport", "stream", "minecraft", "fortnite"],
        "tokens": ["game", "gry"],
        "phrases": [],
    },
    "Food": {
        "roots": ["jedzen", "kuchni", "gotow", "przepis", "food", "restaur"],
        "tokens": ["recipe", "pizza"],
        "phrases": [],
    },
    "Sport & Fitness": {
        "roots": [
            "sport", "fitness", "siłown", "silown", "trening", "biegan",
            "piłk", "pilk", "stadion", "mecz", "kibic", "taniec", "tanec",
        ],
        "tokens": ["gym", "run", "football"],
        "phrases": ["taniec towarzyski"],
    },
    "Tech": {
        "roots": [
            "technolog", "gadżet", "gadzet", "smartfon", "telefon", "komputer",
            "programow", "software", "aplikac", "robot",
        ],
        "tokens": ["tech", "ai"],
        "phrases": ["sztuczna inteligencja", "artificial intelligence"],
    },
    "Education": {
        "roots": [
            "eduk", "nauka", "wiedza", "uczę", "ucze", "szkoł", "szkol",
            "ciekawost", "histori", "wywiad", "sond", "kurs", "ebook",
        ],
        "tokens": ["learn", "school"],
        "phrases": ["platforma edukacyjna"],
    },
    "Travel": {
        "roots": [
            "travel", "podróż", "podroz", "wakac", "turyst", "wyjazd",
            "hotel", "lotnisk",
        ],
        "tokens": ["trip", "flight"],
        "phrases": [],
    },
    "Music": {
        "roots": [
            "muzyk", "piosenk", "melodi", "karaoke", "wokal", "koncert",
            "teledysk", "rap", "śpiew", "spiew",
        ],
        "tokens": ["music", "song", "dj"],
        "phrases": [],
    },
    "Finance": {
        "roots": [
            "finans", "inwest", "pieniąd", "pieniad", "ekonom", "gospodark",
            "rynek", "bank", "inflac", "trading", "krypto", "giełd", "gield",
            "biznes", "energia", "ropa",
        ],
        "tokens": ["finance", "money", "business"],
        "phrases": ["stopy procentowe"],
    },
}


def pl_confidence(text: str, seed_context: bool = False) -> float:
    """
    Legacy-compatible text-only Polish confidence.

    v5 enrichment no longer treats this value alone as authoritative; it
    combines discovery evidence, profile language, captions and post regions.
    """
    t = (text or "").lower()
    score = 10.0 if seed_context else 0.0

    if "🇵🇱" in t:
        score += 30.0

    if POLISH_DIACRITICS_RE.search(t):
        score += 20.0

    tokens = TOKEN_RE.findall(t)
    unique_hits = set(tokens) & POLISH_WORDS
    score += min(30.0, len(unique_hits) * 5.0)

    hashtags = set(re.findall(r"#([\wąćęłńóśźż]+)", t))
    if hashtags & POLISH_HASHTAGS:
        score += 20.0

    return max(0.0, min(95.0, score))


def _pattern_score(text: str, category: str) -> float:
    low = (text or "").lower()
    tokens = TOKEN_RE.findall(low)
    token_set = set(tokens)
    cfg = CATEGORY_PATTERNS[category]

    score = 0.0

    for token in cfg["tokens"]:
        if token in token_set:
            score += 2.0

    for root in cfg["roots"]:
        if any(tok.startswith(root) for tok in tokens):
            score += 1.5

    for phrase in cfg["phrases"]:
        if phrase in low:
            score += 3.0

    return score


def infer_category_scored(
    *,
    display_name: str = "",
    username: str = "",
    bio: str = "",
    captions: Iterable[str] = (),
) -> tuple[str, float, dict[str, float]]:
    """
    Weighted category classification for creator profiles.

    Identity/bio signals are weighted more strongly than one-off captions.
    Repeated caption keywords are capped so one hashtag cannot dominate.
    """
    identity = " ".join([display_name, username, bio]).strip()
    captions = [str(c or "") for c in captions if str(c or "").strip()]

    scores: dict[str, float] = defaultdict(float)

    for category in CATEGORY_PATTERNS:
        scores[category] += 3.0 * _pattern_score(identity, category)

        caption_hits = [
            _pattern_score(caption, category)
            for caption in captions[:20]
        ]
        caption_hits = [v for v in caption_hits if v > 0]
        if caption_hits:
            # Let several recent posts confirm a topic, but cap repetition.
            scores[category] += min(9.0, sum(min(v, 3.0) for v in caption_hits))

    if not scores:
        return "Other", 0.0, {}

    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best_cat, best_score = ordered[0]
    second_score = ordered[1][1] if len(ordered) > 1 else 0.0

    if best_score < 2.0:
        return "Other", 0.0, dict(scores)

    separation = max(0.0, best_score - second_score)
    confidence = min(
        99.0,
        45.0 + min(35.0, best_score * 4.0) + min(19.0, separation * 4.0),
    )
    return best_cat, round(confidence, 1), dict(scores)


def infer_category(text: str) -> str:
    category, _, _ = infer_category_scored(bio=text)
    return category
