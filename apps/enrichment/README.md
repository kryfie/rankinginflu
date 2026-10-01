# InfluRank Enrichment v1

This is the second pipeline stage after discovery.

```text
scanner_queue.json
      ↓
public TikTok profiles
      ↓
exact/current profile fields + latest posts
      ↓
InfluRank normalized store
      ↓
our own metrics
      ↓
apps/web/data/creators.json
```

## Provider

Default:

```text
simple.actor/tiktok-profile-posts
```

The Actor is called in a batch with multiple handles. InfluRank stores the raw
profile/post facts, but does **not** use the provider's ready-made engagement
or median metrics for ranking.

We calculate:
- median views,
- median engagement,
- reach / followers,
- consistency,
- 30D follower growth once enough snapshot history exists.

Pinned posts are excluded from recent-performance metrics when possible.

## Persistent state

Tracked JSON files:

```text
database/data/enriched_creators.json
database/data/posts.json
database/data/creator_snapshots.json
```

Web ranking:

```text
apps/web/data/creators.json
```

Queue statuses:

```text
apps/web/data/scanner_queue.json
```

Full Actor output is diagnostic-only and uploaded as a short-lived Actions
artifact:

```text
apps/enrichment/data/enrichment_raw_full.json
```

## First run

GitHub:

```text
Actions → InfluRank enrichment → Run workflow
```

Recommended first test:

```text
max_profiles = 5
max_posts = 13
refresh_all = false
```

The existing `APIFY_TOKEN` GitHub secret is reused.

## Score during the first month

Momentum requires historical follower snapshots. Until a creator has a
snapshot at least ~30 days old, the score is marked:

```text
provisional_no_30d_history
```

Momentum is omitted rather than faked as zero or 50, and the remaining weights
are re-normalized.
