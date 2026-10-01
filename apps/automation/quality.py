from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
RANKING_PATH = REPO_ROOT / "apps" / "web" / "data" / "creators.json"
REPORT_PATH = REPO_ROOT / "database" / "data" / "quality_report.json"

SUSPICIOUS_BUSINESS_MARKERS = (
    "polska", "poland", "cosmetics", "kosmetyki", "sklep", "shop", "store",
    "carrefour", "lidl", "kaufland", "biedronka", "żabka", "zabka", "starbucks",
    "douglas", "sephora", "hebe", "mobilfox", "pizza hut", "restaurant",
)
PERSONAL_EXCEPTIONS = ("w polsce", "z polski", "polak w", "polka w")


def _load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def build_report() -> dict[str, Any]:
    payload = _load(RANKING_PATH, {"creators": [], "excluded_creators": []})
    creators = payload.get("creators") or []
    excluded = payload.get("excluded_creators") or []

    with_city = [c for c in creators if c.get("city")]
    with_home_city = [c for c in creators if c.get("home_city")]
    with_any_geo = [c for c in creators if float(c.get("geo_confidence") or 0) > 0]

    suspicious = []
    for c in creators:
        identity = f"{c.get('name','')} {c.get('handle','')}".lower()
        if any(x in identity for x in PERSONAL_EXCEPTIONS):
            continue
        hits = sorted({x for x in SUSPICIOUS_BUSINESS_MARKERS if x in identity})
        if hits:
            suspicious.append({
                "rank": c.get("rank"),
                "handle": c.get("handle"),
                "name": c.get("name"),
                "account_type": c.get("account_type"),
                "markers": hits,
            })

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ranking_generated_at": payload.get("generated_at"),
        "ranked_count": len(creators),
        "excluded_count": len(excluded),
        "category_counts": dict(Counter(str(c.get("category") or "Other") for c in creators)),
        "account_type_counts": dict(Counter(str(c.get("account_type") or "unknown") for c in creators)),
        "geo": {
            "with_primary_city": len(with_city),
            "with_home_city": len(with_home_city),
            "with_any_evidence": len(with_any_geo),
            "coverage_pct": round(100 * len(with_city) / max(1, len(creators)), 1),
        },
        "potential_business_leaks": suspicious[:100],
        "potential_business_leak_count": len(suspicious),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", default="report", choices=["report"])
    parser.parse_args()
    report = build_report()
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
