from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]

CREATORS_PATH = REPO_ROOT / "database" / "data" / "enriched_creators.json"
POSTS_PATH = REPO_ROOT / "database" / "data" / "posts.json"
DISCOVERY_RAW_PATH = REPO_ROOT / "apps" / "web" / "data" / "discovery_raw.json"
WEB_RANKING_PATH = REPO_ROOT / "apps" / "web" / "data" / "creators.json"
GEO_EVIDENCE_PATH = REPO_ROOT / "database" / "data" / "geo_evidence.json"


# Text matching is intentionally conservative. POI cityName is accepted
# dynamically, but free-text matching uses a curated Polish city dictionary
# to avoid turning arbitrary words into locations.
CITY_ALIASES = {
    "Warszawa": ["warszawa", "warsaw"],
    "Kraków": ["kraków", "krakow", "cracow"],
    "Łódź": ["łódź", "lodz"],
    "Wrocław": ["wrocław", "wroclaw"],
    "Poznań": ["poznań", "poznan"],
    "Gdańsk": ["gdańsk", "gdansk"],
    "Szczecin": ["szczecin"],
    "Bydgoszcz": ["bydgoszcz"],
    "Lublin": ["lublin"],
    "Białystok": ["białystok", "bialystok"],
    "Katowice": ["katowice"],
    "Gdynia": ["gdynia"],
    "Częstochowa": ["częstochowa", "czestochowa"],
    "Radom": ["radom"],
    "Rzeszów": ["rzeszów", "rzeszow"],
    "Toruń": ["toruń", "torun"],
    "Sosnowiec": ["sosnowiec"],
    "Kielce": ["kielce"],
    "Gliwice": ["gliwice"],
    "Olsztyn": ["olsztyn"],
    "Bielsko-Biała": ["bielsko-biała", "bielsko biała", "bielsko-biala", "bielsko biala"],
    "Zabrze": ["zabrze"],
    "Bytom": ["bytom"],
    "Zielona Góra": ["zielona góra", "zielona gora"],
    "Rybnik": ["rybnik"],
    "Ruda Śląska": ["ruda śląska", "ruda slaska"],
    "Opole": ["opole"],
    "Tychy": ["tychy"],
    "Gorzów Wielkopolski": ["gorzów wielkopolski", "gorzow wielkopolski"],
    "Dąbrowa Górnicza": ["dąbrowa górnicza", "dabrowa gornicza"],
    "Elbląg": ["elbląg", "elblag"],
    "Płock": ["płock", "plock"],
    "Wałbrzych": ["wałbrzych", "walbrzych"],
    "Włocławek": ["włocławek", "wloclawek"],
    "Tarnów": ["tarnów", "tarnow"],
    "Chorzów": ["chorzów", "chorzow"],
    "Koszalin": ["koszalin"],
    "Kalisz": ["kalisz"],
    "Legnica": ["legnica"],
    "Grudziądz": ["grudziądz", "grudziadz"],
    "Słupsk": ["słupsk", "slupsk"],
    "Jaworzno": ["jaworzno"],
    "Jastrzębie-Zdrój": ["jastrzębie-zdrój", "jastrzebie zdroj"],
    "Nowy Sącz": ["nowy sącz", "nowy sacz"],
    "Jelenia Góra": ["jelenia góra", "jelenia gora"],
    "Siedlce": ["siedlce"],
    "Mysłowice": ["mysłowice", "myslowice"],
    "Piła": ["piła"],
    "Konin": ["konin"],
    "Piotrków Trybunalski": ["piotrków trybunalski", "piotrkow trybunalski"],
    "Inowrocław": ["inowrocław", "inowroclaw"],
    "Lubin": ["lubin"],
    "Ostrów Wielkopolski": ["ostrów wielkopolski", "ostrow wielkopolski"],
    "Suwałki": ["suwałki", "suwalki"],
    "Gniezno": ["gniezno"],
    "Stargard": ["stargard"],
    "Pruszków": ["pruszków", "pruszkow"],
    "Zakopane": ["zakopane"],
    "Sopot": ["sopot"],
    "Kołobrzeg": ["kołobrzeg", "kolobrzeg"],
    "Świnoujście": ["świnoujście", "swinoujscie"],
    "Mielno": ["mielno"],
    "Międzyzdroje": ["międzyzdroje", "miedzyzdroje"],
    "Hel": ["hel"],
    "Władysławowo": ["władysławowo", "wladyslawowo"],
    "Karpacz": ["karpacz"],
    "Szklarska Poręba": ["szklarska poręba", "szklarska poreba"],
}

# Avoid very short/ambiguous aliases in free text. Example: "Piła" can be
# a noun/verb form, "Hel" occurs in unrelated words. These still work via POI.
TEXT_ALIAS_BLOCKLIST = {"piła", "hel"}

WORDISH = re.compile(r"[a-ząćęłńóśźż0-9_]+", re.IGNORECASE)


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _username(value: Any) -> str:
    return str(value or "").strip().lstrip("@").lower()


def _norm(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = unicodedata.normalize("NFKC", text)
    return re.sub(r"\s+", " ", text)


def _text_city_hits(text: Any) -> set[str]:
    low = _norm(text)
    if not low:
        return set()

    hits: set[str] = set()

    # Pad to make single-token boundary checks robust.
    padded = f" {low} "

    for city, aliases in CITY_ALIASES.items():
        for alias in aliases:
            a = _norm(alias)
            if a in TEXT_ALIAS_BLOCKLIST:
                continue

            # Hashtags often remove spaces/hyphens, so test both normal and
            # collapsed variants.
            variants = {a, a.replace(" ", ""), a.replace("-", "")}

            if any(
                (
                    f" {variant} " in padded
                    or f"#{variant}" in low
                    or f"@{variant}" in low
                )
                for variant in variants
            ):
                hits.add(city)
                break

            # Normal phrase boundary for multi-word names.
            if " " in a and a in low:
                hits.add(city)
                break

    return hits



VENUE_MARKERS = (
    "mor ", "mop ", "restauracja", "restaurant", "hotel", "hostel",
    "galeria", "centrum handlowe", "shopping", "sklep", "market",
    "stadion", "arena", "park rozrywki", "dworzec", "lotnisko", "airport",
    "stacja ", "studio", "salon", "klinika", "szpital", "school", "szkoła",
    "muzeum", "museum", "bar ", "cafe", "café", "kawiarnia", "club", "klub",
)


def _canonical_known_city(value: Any) -> str:
    hits = _text_city_hits(value)
    if len(hits) == 1:
        return next(iter(hits))
    return ""


def _normalize_locality_label(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""

    low = _norm(raw)
    for prefix in ("gmina ", "miasto ", "city of "):
        if low.startswith(prefix):
            raw = raw[len(prefix):].strip()
            low = _norm(raw)
            break

    known = _canonical_known_city(raw)
    if known:
        return known

    if any(marker in low for marker in VENUE_MARKERS):
        return ""
    if re.search(r"\d", raw):
        return ""
    if len(raw) > 48 or len(raw.split()) > 4:
        return ""
    if len(raw) < 3:
        return ""

    # Reject acronym-led road/service-area style POIs such as
    # "MOR Wrotki Mogilnice" even when no marker matched after punctuation.
    first = raw.split()[0]
    if first.isupper() and 2 <= len(first) <= 5:
        return ""

    return raw

def _poi_city(poi: Any) -> str:
    """Return a normalized Polish locality from TikTok POI metadata."""
    if not isinstance(poi, dict):
        return ""

    poi_name_raw = str(poi.get("poiName") or "").strip()
    address_raw = str(poi.get("address") or "").strip()
    city_raw = str(poi.get("cityName") or "").strip()

    address = _norm(address_raw)
    is_pl = "poland" in address or "polska" in address
    if not is_pl:
        is_pl = bool(
            _text_city_hits(address_raw)
            or _text_city_hits(city_raw)
            or _text_city_hits(poi_name_raw)
        )
    if not is_pl:
        return ""

    # Explicit cityName is preferred, but normalize it and reject venue-like
    # strings rather than blindly publishing provider text as a city.
    city = _normalize_locality_label(city_raw)
    address_hits = _text_city_hits(address_raw)
    name_hits = _text_city_hits(poi_name_raw)

    if city:
        city_known = _canonical_known_city(city)
        if address_hits and city_known and city_known not in address_hits:
            return ""
        # Conflicting country-only POI metadata is safer left unknown.
        if address in {"polska", "poland"} and name_hits:
            name_city = next(iter(name_hits)) if len(name_hits) == 1 else ""
            if name_city and city_known and name_city != city_known:
                return ""
        return city_known or city

    # A city explicitly present in the address is strong evidence.
    if len(address_hits) == 1:
        return next(iter(address_hits))

    # Recover smaller localities when POI name equals the first address segment.
    first_segment = str(address_raw.split(",", 1)[0]).strip()
    if poi_name_raw and first_segment and _norm(poi_name_raw) == _norm(first_segment):
        return _normalize_locality_label(poi_name_raw)

    # Known-city POI names are useful when address only contains region/country.
    if len(name_hits) == 1:
        return next(iter(name_hits))

    return ""


def _event_key(username: str, source: str, ref: str, city: str) -> str:
    return f"{username}|{source}|{ref}|{_norm(city)}"


def _add_event(
    events: dict[str, dict[str, Any]],
    *,
    username: str,
    city: str,
    source: str,
    ref: str,
    weight: float,
    observed_at: str | None = None,
) -> None:
    username = _username(username)
    city = str(city or "").strip()
    if not username or not city:
        return

    key = _event_key(username, source, ref, city)
    if key in events:
        # Same post/bio evidence must not compound across daily runs.
        if observed_at and not events[key].get("observed_at"):
            events[key]["observed_at"] = observed_at
        return

    events[key] = {
        "key": key,
        "username": username,
        "city": city,
        "source": source,
        "ref": str(ref or ""),
        "weight": float(weight),
        "observed_at": observed_at,
    }


def _collect_bio_events(
    events: dict[str, dict[str, Any]],
    creators: list[dict[str, Any]],
) -> None:
    for creator in creators:
        if not isinstance(creator, dict):
            continue
        username = _username(creator.get("username"))
        bio = creator.get("bio")
        for city in _text_city_hits(bio):
            _add_event(
                events,
                username=username,
                city=city,
                source="bio",
                ref="current_bio",
                weight=95.0,
                observed_at=creator.get("last_enriched_at"),
            )


def _collect_post_events(
    events: dict[str, dict[str, Any]],
    posts: list[dict[str, Any]],
) -> None:
    for post in posts:
        if not isinstance(post, dict):
            continue

        username = _username(post.get("username"))
        post_id = str(post.get("id") or "").strip()
        if not username or not post_id:
            continue

        caption = str(post.get("caption") or "")
        hashtags = post.get("hashtags") or []
        text = " ".join(
            [caption]
            + [
                str(tag.get("name") or tag.get("title") or "")
                if isinstance(tag, dict)
                else str(tag or "")
                for tag in hashtags
            ]
        )

        for city in _text_city_hits(text):
            _add_event(
                events,
                username=username,
                city=city,
                source="post_text",
                ref=post_id,
                weight=18.0,
                observed_at=post.get("timestamp") or post.get("scraped_at"),
            )


def _collect_discovery_events(
    events: dict[str, dict[str, Any]],
    discovery: dict[str, Any],
) -> None:
    rows = discovery.get("posts", [])
    if not isinstance(rows, list):
        return

    for post in rows:
        if not isinstance(post, dict):
            continue

        channel = post.get("channel")
        if not isinstance(channel, dict):
            continue

        username = _username(channel.get("username"))
        post_id = str(post.get("id") or "").strip()
        if not username or not post_id:
            continue

        city = _poi_city(post.get("poi"))
        if city:
            _add_event(
                events,
                username=username,
                city=city,
                source="poi",
                ref=post_id,
                weight=75.0,
                observed_at=post.get("uploadedAtFormatted"),
            )

        title = post.get("title")
        tags = post.get("hashtags") or []
        text = " ".join([str(title or "")] + [str(tag or "") for tag in tags])
        for city in _text_city_hits(text):
            _add_event(
                events,
                username=username,
                city=city,
                source="discovery_text",
                ref=post_id,
                weight=15.0,
                observed_at=post.get("uploadedAtFormatted"),
            )


def _score_username(
    username: str,
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    by_city: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for event in events:
        if _username(event.get("username")) != username:
            continue
        city = str(event.get("city") or "").strip()
        if city:
            by_city[city].append(event)

    scored = []
    for city, rows in by_city.items():
        sources = {str(row.get("source") or "") for row in rows}
        post_refs = {
            str(row.get("ref") or "")
            for row in rows
            if row.get("source") in {"post_text", "poi", "discovery_text"}
        }

        # Weight is capped by source type so one creator mentioning a city in
        # ten captions doesn't become "certain" purely through repetition.
        bio_score = 95.0 if "bio" in sources else 0.0
        poi_count = sum(1 for row in rows if row.get("source") == "poi")
        text_posts = sum(
            1 for row in rows
            if row.get("source") in {"post_text", "discovery_text"}
        )

        poi_score = min(90.0, 65.0 + max(0, poi_count - 1) * 10.0) if poi_count else 0.0
        text_score = min(72.0, text_posts * 18.0)

        score = max(bio_score, poi_score, text_score)

        # Independent source agreement is especially strong.
        if "bio" in sources and ("poi" in sources or text_posts >= 1):
            score = min(100.0, score + 5.0)
        elif "poi" in sources and text_posts >= 1:
            score = min(95.0, score + 8.0)

        scored.append(
            {
                "city": city,
                "confidence": round(score, 1),
                "sources": sorted(sources),
                "evidence_count": len(rows),
                "post_count": len(post_refs),
                "home_city_signal": "bio" in sources,
            }
        )

    scored.sort(
        key=lambda row: (
            float(row["confidence"]),
            int(row["home_city_signal"]),
            int(row["post_count"]),
        ),
        reverse=True,
    )

    # IMPORTANT: a TikTok POI describes the location of a post, not the
    # creator's home/base. A single POI must therefore never become the
    # public "city" by itself. Promote a city only when the evidence is
    # stable enough to describe the creator rather than one piece of content.
    primary_candidates = []
    for row in scored:
        sources = set(row.get("sources") or [])
        evidence_count = int(row.get("evidence_count") or 0)
        post_count = int(row.get("post_count") or 0)

        stable = False

        # Explicit profile bio is the strongest home/base signal.
        if row.get("home_city_signal"):
            stable = True

        # Two or more distinct POI posts in the same city indicate a
        # recurring location rather than a one-off visit.
        elif "poi" in sources:
            poi_rows = [
                event for event in by_city.get(row["city"], [])
                if event.get("source") == "poi"
            ]
            poi_post_refs = {
                str(event.get("ref") or "")
                for event in poi_rows
                if event.get("ref")
            }
            if len(poi_post_refs) >= 2:
                stable = True

            # Independent agreement between POI and textual evidence is also
            # enough to promote the city.
            if any(
                source in sources
                for source in {"post_text", "discovery_text"}
            ):
                stable = True

        # Repeated textual mentions across several distinct posts can also
        # establish a stable content/base association.
        elif post_count >= 4 and evidence_count >= 4:
            stable = True

        if stable and float(row.get("confidence") or 0) >= 60:
            primary_candidates.append(row)

    primary = primary_candidates[0] if primary_candidates else None
    home = next(
        (row for row in scored if row.get("home_city_signal")),
        None,
    )

    return {
        "primary_city": primary["city"] if primary else None,
        # Top-level confidence/sources describe the published primary city.
        # One-off content evidence keeps its own confidence in content_cities.
        "geo_confidence": primary["confidence"] if primary else 0.0,
        "geo_sources": primary["sources"] if primary else [],
        "home_city": home["city"] if home and home["confidence"] >= 90 else None,
        "content_cities": scored[:5],
    }


def harvest() -> dict[str, Any]:
    run_at = utcnow()

    creators_payload = _load(CREATORS_PATH, {"creators": []})
    posts_payload = _load(POSTS_PATH, {"posts": []})
    discovery_payload = _load(DISCOVERY_RAW_PATH, {"posts": []})
    web_payload = _load(WEB_RANKING_PATH, {"creators": [], "excluded_creators": []})
    evidence_payload = _load(GEO_EVIDENCE_PATH, {"events": []})

    creators = creators_payload.get("creators", [])
    posts = posts_payload.get("posts", [])
    old_events = evidence_payload.get("events", [])

    creators = creators if isinstance(creators, list) else []
    posts = posts if isinstance(posts, list) else []
    old_events = old_events if isinstance(old_events, list) else []

    events: dict[str, dict[str, Any]] = {
        str(row.get("key")): dict(row)
        for row in old_events
        if isinstance(row, dict) and row.get("key")
    }

    before = len(events)
    _collect_bio_events(events, creators)
    _collect_post_events(events, posts)
    _collect_discovery_events(events, discovery_payload)
    added = len(events) - before

    events_list = sorted(
        events.values(),
        key=lambda row: (
            _username(row.get("username")),
            str(row.get("city") or ""),
            str(row.get("source") or ""),
            str(row.get("ref") or ""),
        ),
    )

    by_username = defaultdict(list)
    for event in events_list:
        by_username[_username(event.get("username"))].append(event)

    geo_by_username = {
        username: _score_username(username, rows)
        for username, rows in by_username.items()
        if username
    }

    # Enriched creator database gets the full geo block.
    creators_out = []
    for creator in creators:
        if not isinstance(creator, dict):
            continue
        row = dict(creator)
        username = _username(row.get("username"))
        geo = geo_by_username.get(
            username,
            {
                "primary_city": None,
                "geo_confidence": 0.0,
                "geo_sources": [],
                "home_city": None,
                "content_cities": [],
            },
        )
        row["geo"] = geo
        row["primary_city"] = geo["primary_city"]
        row["geo_confidence"] = geo["geo_confidence"]
        row["home_city"] = geo["home_city"]
        creators_out.append(row)

    creators_payload["creators"] = creators_out
    meta = creators_payload.get("meta", {})
    meta = dict(meta) if isinstance(meta, dict) else {}
    meta["geo_updated_at"] = run_at
    creators_payload["meta"] = meta
    _write(CREATORS_PATH, creators_payload)

    # Public ranking gets only the fields useful to the UI/search.
    public_creators = web_payload.get("creators", [])
    public_creators = public_creators if isinstance(public_creators, list) else []

    public_out = []
    public_with_city = 0
    for creator in public_creators:
        if not isinstance(creator, dict):
            continue
        row = dict(creator)
        username = _username(row.get("handle"))
        geo = geo_by_username.get(username, {})
        row["city"] = geo.get("primary_city")
        row["home_city"] = geo.get("home_city")
        row["geo_confidence"] = geo.get("geo_confidence", 0.0)
        row["geo_sources"] = geo.get("geo_sources", [])
        row["content_cities"] = geo.get("content_cities", [])
        if row["city"]:
            public_with_city += 1
        public_out.append(row)

    web_payload["creators"] = public_out
    web_payload["geo_note"] = (
        "City is inferred conservatively from stable public profile/content signals. "
        "A single TikTok POI is treated only as a content location and does not "
        "become the creator city by itself."
    )
    web_payload["geo_updated_at"] = run_at
    _write(WEB_RANKING_PATH, web_payload)

    geo_payload = {
        "version": 1,
        "updated_at": run_at,
        "events_count": len(events_list),
        "creators_with_any_geo_evidence": len(geo_by_username),
        "ranked_creators_with_primary_city": public_with_city,
        "events": events_list,
    }
    _write(GEO_EVIDENCE_PATH, geo_payload)

    return {
        "events_added": added,
        "events_total": len(events_list),
        "creators_with_any_geo_evidence": len(geo_by_username),
        "ranked_creators_with_primary_city": public_with_city,
        "ranked_creators_total": len(public_out),
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="influrank-geo")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("harvest")
    args = parser.parse_args()

    if args.command == "harvest":
        result = harvest()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
