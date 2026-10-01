# InfluRank Discovery v1

This module discovers TikTok creator candidates and prepares them for the existing InfluRank profile scanner.

## What it does

1. Sends a list of Polish TikTok search seeds to the configured Apify Actor.
2. Receives TikTok post/search results.
3. Deduplicates creators by stable TikTok user ID (username fallback).
4. Keeps discovery signals such as Polish subtitles, Polish hashtags and Polish POI.
5. Filters by a configurable minimum follower count.
6. Writes:
   - `apps/web/data/discovery_raw.json`
   - `apps/web/data/discovery_candidates.json`
   - `apps/web/data/scanner_queue.json`

## Important

`channel.verified` returned by the discovery provider is stored only for diagnostics.
It is NOT authoritative and must not be used as the verified badge in InfluRank.

The existing InfluRank profile scanner should be the authoritative source for:
- verified status,
- current follower count,
- bio,
- total likes,
- post count,
- other profile fields.

## Setup

From the repository root:

```powershell
python -m pip install -r apps/discovery/requirements.txt
$env:APIFY_TOKEN="YOUR_TOKEN"
python -m apps.discovery run --max-items 100 --min-followers 10000
```

Larger run:

```powershell
python -m apps.discovery run --max-items 1000 --min-followers 10000
```

Alternative sort test:

```powershell
python -m apps.discovery run --max-items 1000 --sort-type MOST_LIKED
```

## Seeds

Edit:

```text
apps/discovery/seeds.json
```

The default list deliberately mixes broad Polish discovery terms and category-oriented searches.

## Environment variables

```text
APIFY_TOKEN                       required
APIFY_DISCOVERY_ACTOR             default: apidojo~tiktok-scraper-api
DISCOVERY_LOCATION                default: PL
DISCOVERY_DATE_RANGE              default: LAST_THREE_MONTHS
DISCOVERY_SORT_TYPE               default: RELEVANCE
DISCOVERY_MIN_FOLLOWERS           default: 10000
DISCOVERY_MAX_ITEMS               default: 1000
DISCOVERY_TIMEOUT_SECONDS         default: 180
```

CLI arguments override the main discovery settings for a run.

## Output example

`discovery_candidates.json`:

```json
{
  "meta": {
    "stats": {
      "posts_in": 1000,
      "unique_creators": 650,
      "below_min_followers": 300,
      "accepted_candidates": 350
    }
  },
  "creators": [
    {
      "tiktok_id": "123",
      "username": "creator",
      "followers": 120000,
      "found_by": ["polskatiktok", "polska beauty"],
      "posts_seen": 3,
      "polish_signal_count": 2,
      "polish_signals": ["hashtag", "subtitle_pl"]
    }
  ]
}
```

The numbers above are only an output-format example, not expected benchmark values.

## Next integration step

`scanner_queue.json` is intentionally provider-agnostic. Each item starts with:

```json
{
  "username": "creator",
  "status": "pending_profile_scan"
}
```

Do not automatically loop the current profile scanner until its output behavior is confirmed to append/upsert rather than overwrite `creators.json`.
