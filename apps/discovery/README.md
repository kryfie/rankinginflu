# InfluRank Discovery v2

Discovery is intentionally separate from the final Influence Score.

## Why v2 is different

Each seed is now sent to the provider in a separate Actor run.

So:

```text
polskatiktok -> N results
tiktokpolska -> N results
polska beauty -> N results
...
```

Only after all completed seeds do we deduplicate creators.

This fixes the v1 problem where `maxItems=10` applied to the whole list of
keywords and the provider could fill the entire quota from the first seed.

## Persistent creator universe

`discovery_candidates.json` is an upsert registry, not a one-run replacement.
Creators found in earlier runs are kept.

`scanner_queue.json` also preserves downstream statuses.

## Files

Committed:
- `apps/web/data/discovery_candidates.json`
- `apps/web/data/scanner_queue.json`
- `apps/web/data/discovery_raw.json` (compact diagnostic data)

Not committed:
- `apps/discovery/data/discovery_raw_full.json`

The full provider payload is uploaded as a short-lived GitHub Actions artifact.

## Provider verification flag

The discovery provider's `verified` value is not considered authoritative.
InfluRank must confirm the TikTok badge independently during profile enrichment.
