from __future__ import annotations

from datetime import datetime, timezone

from .classification import classify_all_creators
from .config import REPO_ROOT
from .ranking import build_excluded_creators, build_web_ranking
from .store import load_json, write_json


CREATORS_PATH = REPO_ROOT / "database" / "data" / "enriched_creators.json"
POSTS_PATH = REPO_ROOT / "database" / "data" / "posts.json"
SNAPSHOTS_PATH = REPO_ROOT / "database" / "data" / "creator_snapshots.json"
QUEUE_PATH = REPO_ROOT / "apps" / "web" / "data" / "scanner_queue.json"
OUTPUT_PATH = REPO_ROOT / "apps" / "web" / "data" / "creators.json"


def main() -> int:
    creators_payload = load_json(CREATORS_PATH, {"creators": []})
    posts_payload = load_json(POSTS_PATH, {"posts": []})
    snapshots_payload = load_json(SNAPSHOTS_PATH, {"snapshots": []})
    queue_payload = load_json(QUEUE_PATH, {"items": []})

    creators = creators_payload.get("creators", [])
    posts = posts_payload.get("posts", [])
    snapshots = snapshots_payload.get("snapshots", [])
    queue_items = queue_payload.get("items", [])

    creators = creators if isinstance(creators, list) else []
    posts = posts if isinstance(posts, list) else []
    snapshots = snapshots if isinstance(snapshots, list) else []
    queue_items = queue_items if isinstance(queue_items, list) else []

    classified = classify_all_creators(
        creators,
        posts,
        queue_items,
    )

    ranking = build_web_ranking(
        classified,
        posts,
        snapshots,
    )
    excluded = build_excluded_creators(classified)

    generated_at = datetime.now(timezone.utc).isoformat()

    write_json(
        CREATORS_PATH,
        {
            "meta": {
                **(creators_payload.get("meta") or {}),
                "updated_at": generated_at,
                "count": len(classified),
                "classification_version": "v5",
            },
            "creators": classified,
        },
    )

    write_json(
        OUTPUT_PATH,
        {
            "generated_at": generated_at,
            "source": "influRank-rebuild-v5",
            "score_note": (
                "Influence Score uses InfluRank-calculated raw-post metrics. "
                "Consistency uses log-view MAD. Momentum is omitted until "
                "approximately 30 days of follower history exist. "
                "Only ranking-eligible person/creator_brand accounts are scored."
            ),
            "creators": ranking,
            "excluded_creators": excluded,
        },
    )

    print(
        f"Reclassified/rebuilt: creators={len(classified)} "
        f"posts={len(posts)} snapshots={len(snapshots)} "
        f"ranking={len(ranking)} excluded={len(excluded)}"
    )

    print()
    print("CLASSIFICATION")
    for creator in classified[:50]:
        print(
            f"@{creator['username']:<24} "
            f"type={creator.get('account_type','?'):<14} "
            f"category={creator.get('category','?'):<18} "
            f"PL={float(creator.get('pl_confidence') or 0):>5.1f} "
            f"eligible={creator.get('ranking_eligible')}"
        )

    print()
    print("RANKING")
    for row in ranking[:20]:
        print(
            f"#{row['rank']:>2} @{row['handle']:<24} "
            f"score={row['score']:>5.1f} "
            f"followers={row['followers']:<9} "
            f"medianViews={row['views']:<10.0f} "
            f"eng={row['engagement']:.2f}% "
            f"consistency={row['consistency_index']:.1f}"
        )

    if excluded:
        print()
        print("EXCLUDED")
        for row in excluded[:30]:
            print(
                f"@{row['handle']:<24} "
                f"type={row['account_type']:<14} "
                f"reasons={','.join(row['eligibility_reasons'])}"
            )

    print(f"Output: {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
