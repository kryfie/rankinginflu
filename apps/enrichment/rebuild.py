from __future__ import annotations

from datetime import datetime, timezone

from .config import REPO_ROOT
from .ranking import build_web_ranking
from .store import load_json, write_json


CREATORS_PATH = REPO_ROOT / "database" / "data" / "enriched_creators.json"
POSTS_PATH = REPO_ROOT / "database" / "data" / "posts.json"
SNAPSHOTS_PATH = REPO_ROOT / "database" / "data" / "creator_snapshots.json"
OUTPUT_PATH = REPO_ROOT / "apps" / "web" / "data" / "creators.json"


def main() -> int:
    creators_payload = load_json(CREATORS_PATH, {"creators": []})
    posts_payload = load_json(POSTS_PATH, {"posts": []})
    snapshots_payload = load_json(SNAPSHOTS_PATH, {"snapshots": []})

    creators = creators_payload.get("creators", [])
    posts = posts_payload.get("posts", [])
    snapshots = snapshots_payload.get("snapshots", [])

    ranking = build_web_ranking(
        creators if isinstance(creators, list) else [],
        posts if isinstance(posts, list) else [],
        snapshots if isinstance(snapshots, list) else [],
    )

    generated_at = datetime.now(timezone.utc).isoformat()

    write_json(
        OUTPUT_PATH,
        {
            "generated_at": generated_at,
            "source": "influRank-rebuild-v2",
            "score_note": (
                "Influence Score uses InfluRank-calculated raw-post metrics. "
                "Consistency uses log-view MAD. Momentum is omitted until "
                "approximately 30 days of follower history exist."
            ),
            "creators": ranking,
        },
    )

    print(
        f"Rebuilt ranking: creators={len(creators)} "
        f"posts={len(posts)} snapshots={len(snapshots)} "
        f"ranking={len(ranking)}"
    )

    for row in ranking[:20]:
        print(
            f"#{row['rank']:>2} @{row['handle']:<24} "
            f"score={row['score']:>5.1f} "
            f"followers={row['followers']:<9} "
            f"medianViews={row['views']:<10.0f} "
            f"eng={row['engagement']:.2f}% "
            f"consistency={row['consistency_index']:.1f}"
        )

    print(f"Output: {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
