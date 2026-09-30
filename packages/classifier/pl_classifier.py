import re

POLISH_HASHTAGS = {
    "polska", "poland", "polskitiktok", "warszawa", "krakow", "wroclaw",
    "poznan", "gdansk", "szczecin", "lodz", "katowice", "polak", "polka",
    "polski", "polskie", "polsku"
}
POLISH_WORDS = {
    "jest", "nie", "tak", "dla", "jak", "mam", "moja", "moje", "mój",
    "czy", "się", "ale", "też", "tylko", "dzisiaj", "polska", "polski",
    "polskie", "warszawa", "kraków", "wrocław", "poznań", "gdańsk", "szczecin"
}
CATEGORY_KEYWORDS = {
    "Entertainment": ["comedy", "komedia", "humor", "meme", "skecz", "funny", "rozrywka"],
    "Lifestyle": ["lifestyle", "daily", "vlog", "życie", "life"],
    "Beauty": ["beauty", "makeup", "makijaż", "kosmet", "skincare", "uroda"],
    "Fashion": ["fashion", "moda", "outfit", "style", "stylizacja"],
    "Gaming": ["gaming", "game", "gry", "gracz", "stream", "esport"],
    "Food": ["food", "jedzenie", "kuchnia", "gotowanie", "recipe", "przepis"],
    "Sport & Fitness": ["sport", "fitness", "gym", "siłown", "trening", "biegan", "run", "football", "piłka"],
    "Tech": ["tech", "technolog", "gadżet", "smartfon", "telefon", "komputer", "ai"],
    "Education": ["eduk", "nauka", "wiedza", "uczę", "learn", "school", "szkoł"],
    "Travel": ["travel", "podróż", "wakacje", "trip", "lot", "hotel"],
    "Music": ["music", "muzyka", "piosenk", "rap", "sing", "wokal", "dj"],
    "Finance": ["finanse", "finance", "inwest", "biznes", "business", "pieniądze", "money", "trading"],
}

def pl_confidence(text: str, seed_context: bool = False) -> float:
    t = (text or "").lower()
    score = 20.0 if seed_context else 0.0
    if "🇵🇱" in t:
        score += 35
    if re.search(r"[ąćęłńóśźż]", t):
        score += 25
    tokens = set(re.findall(r"[a-ząćęłńóśźż]+", t))
    score += min(30, len(tokens & POLISH_WORDS) * 6)
    hashtags = set(re.findall(r"#([\wąćęłńóśźż]+)", t))
    if hashtags & POLISH_HASHTAGS:
        score += 25
    if any(city in t for city in ["warszawa","kraków","wrocław","poznań","gdańsk","szczecin","łódź","katowice","polska"]):
        score += 15
    return max(0.0, min(100.0, score))

def infer_category(text: str) -> str:
    t = (text or "").lower()
    scores = {cat: sum(1 for kw in words if kw in t) for cat, words in CATEGORY_KEYWORDS.items()}
    best = max(scores, key=scores.get) if scores else ""
    return best if scores.get(best, 0) > 0 else ""
