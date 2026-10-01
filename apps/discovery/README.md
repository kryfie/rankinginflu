# InfluRank Discovery v4

## Goal

Discovery answers one question:

> Which TikTok accounts are worth sending to the more expensive profile/post enrichment stage?

It is intentionally conservative. A generic `#polska` match is not enough.

## Seed-by-seed

Each seed has its own provider call:

```text
polskatiktok → N rows
tiktokpolska → N rows
polska       → N rows
...
```

Then InfluRank deduplicates creators by TikTok user ID.

## Strong vs weak Polish evidence

### Strong

Any of these can qualify a candidate:

```text
subtitle_pl   TikTok captions marked as Polish
poi_pl        TikTok POI explicitly in Poland
flag_pl       🇵🇱 in title/channel/hashtags
polish_text   Polish-language text detected in the post caption
```

### Weak

These remain useful for diagnostics/discovery, but do NOT qualify alone:

```text
#polska / #polish / #polskatiktok
word Polska / Poland / Polish
Polish marker in channel name
```

This is deliberate. The query `polska` can return foreign content where
"Polska" is a person's/name/topic rather than Polish content.

Default gate:

```text
followers >= 10,000
strong PL signals >= 1
PL confidence >= 50
```

## Demo rows

Provider rows such as:

```json
{"demo": true}
```

are never treated as posts or creators.

Per-seed metadata records:

```text
rows_returned
usable_posts
demo_rows
status = productive | demo_only | no_usable_rows
```

The full diagnostic artifact still keeps provider rows so we can see what the
provider returned.

## v3 cleanup

When v4 runs for the first time, it re-evaluates creators from the immediately
previous compact discovery file.

Weak-only pending creators are marked `discovery_eligible=false` and removed
from `scanner_queue.json`.

Already enriched/profile-scanned creators are preserved.

## Seed list

`polandtiktok` was removed after returning demo-only rows in the tested provider.

Current indices:

```text
0 polskatiktok
1 tiktokpolska
2 polska
3 polishtiktok
4 polski humor
5 polska beauty
6 polska moda
7 polska fitness
8 polska gaming
9 polska tech
10 polska edukacja
11 polska jedzenie
12 polska podróże
13 polska muzyka
14 polska finanse
```

After the already completed 0/1/2 searches, the next batch is:

```text
start_seed = 3
max_seeds = 2
```

which runs:

```text
polishtiktok
polski humor
```
