# InfluRank PL

MVP polskiego rankingu twórców TikTok.

## Aktualna architektura

```text
Apify search discovery
        ↓
seed-by-seed discovery
        ↓
deduplikacja po TikTok user ID
        ↓
lekki PL filter + min followers
        ↓
cumulative candidate registry
        ↓
scanner_queue.json
        ↓
public profile enrichment (kolejny etap)
        ↓
recent posts / metrics
        ↓
Influence Score
        ↓
Netlify frontend
``

## Najważniejsze katalogi

```text
apps/web/          frontend Netlify + dane publikowane
apps/discovery/    discovery nowych kandydatów
apps/scanner/      własny public-profile scanner
packages/          klasyfikacja, modele i ranking
database/          eksperymentalny schemat SQLite
.github/workflows/ GitHub Actions
```

## Discovery v2

Najważniejsza zmiana: **każdy seed ma osobny request do providera**.

`results_per_seed=10` oznacza faktycznie do 10 wyników z każdego wykonanego seeda,
a nie 10 wyników łącznie dla całej listy.

Lista seedów:

```text
apps/discovery/seeds.json
```

### Dane są kumulowane

`apps/web/data/discovery_candidates.json` jest rejestrem kandydatów.
Kolejny run dopisuje/aktualizuje twórców zamiast kasować wcześniejsze odkrycia.

`apps/web/data/scanner_queue.json` zachowuje status profilu pomiędzy runami.

### Raw data

Do repo trafia tylko kompaktowy:

```text
apps/web/data/discovery_raw.json
```

Pełny payload providera jest tylko 7-dniowym artifactem GitHub Actions.

## Jak uruchomić discovery

GitHub:

```text
Actions
→ InfluRank discovery
→ Run workflow
→ Branch: main
```

Parametry:

```text
results_per_seed = 10
max_seeds = 1        # bezpieczny test; 0 = wszystkie seedy
min_followers = 10000
min_pl_signals = 1
sort_type = RELEVANCE
date_range = LAST_THREE_MONTHS
```

Workflow wykonuje się i zapisuje dane wyłącznie na branchu `main`.

## APIFY_TOKEN

GitHub:

```text
Settings
→ Secrets and variables
→ Actions
→ Repository secrets
→ APIFY_TOKEN
```

Nie zapisuj prawdziwego tokena w repo.

## Ważne o verified

Pole `verified` z discovery providera nie jest traktowane jako wiarygodne.
InfluRank ma potwierdzać badge podczas niezależnego profile enrichment.

## Public profile scanner

Ręczny test:

```text
Actions → Test TikTok profile
```

Domyślnie `posts=0`, czyli sprawdzamy profil bez próby pobierania postów przez
browser fallback. TikTok może ograniczać publiczny dostęp; scanner nie rozwiązuje
CAPTCHA i nie obchodzi 403/429.

## Influence Score

Obecny kod ma wersję eksperymentalną. Finalny score powinien być liczony dopiero
po zebraniu reprezentatywnej grupy creatorów i historii snapshotów.

Planowane filary:
- reach,
- engagement,
- audience,
- momentum,
- consistency.

Dla metryk postów używamy median, nie średnich.

## Netlify

`netlify.toml` publikuje `apps/web`.

## Kolejny etap

Po stabilnym discovery:
1. automatyczny profile enrichment z `scanner_queue.json`,
2. jednoznaczny PL Confidence,
3. creator vs firma/media,
4. kategorie,
5. ostatnie 10–30 postów,
6. ranking + historia dzienna.


## Enrichment v1

After discovery, run:

```text
Actions → InfluRank enrichment
```

Recommended first test:

```text
max_profiles = 5
max_posts = 13
refresh_all = false
```

The workflow reads `scanner_queue.json`, batches the pending handles into the
profile/post Actor, normalizes profile and post data, writes daily follower
snapshots, calculates InfluRank's own recent-post metrics, and regenerates:

```text
apps/web/data/creators.json
```

Persistent normalized data is stored in:

```text
database/data/enriched_creators.json
database/data/posts.json
database/data/creator_snapshots.json
```

During the first ~30 days, momentum is unavailable. Influence Score is therefore
marked provisional and the remaining score weights are re-normalized rather
than inventing a momentum value.


## Ranking rebuild / consistency v2

Consistency no longer uses raw coefficient-of-variation on views. TikTok view
distributions are heavy-tailed, so one viral post could previously collapse
consistency toward zero.

InfluRank now uses:
1. log10(view count),
2. median,
3. median absolute deviation (MAD),
4. a robust 0-100 consistency index.

The final consistency component is then normalized against the current cohort.

After updating the ranking code you do **not** need to call Apify again.
Use:

```text
Actions → Rebuild InfluRank ranking → Run workflow
```

It rebuilds `apps/web/data/creators.json` from the already stored normalized
profile/post/snapshot files and costs no provider run.


## Discovery v4 quality gate

Discovery now distinguishes strong Polish evidence (PL subtitles, Polish POI,
🇵🇱, or detected Polish-language caption text) from weak keyword matches such
as `#polska`.

Weak-only matches are not sent to enrichment. Provider demo rows are ignored.
The first v4 run also revalidates the previous compact discovery batch so weak
v3 false positives do not remain pending in `scanner_queue.json`.

`polandtiktok` was removed from the default seeds after returning demo-only
provider rows in the tested run.


## Creator classification / eligibility v5

Before a creator can enter the public ranking, InfluRank now stores:

```text
discovery_pl_confidence
enrichment_pl_confidence
pl_confidence
category
category_confidence
account_type
account_type_confidence
ranking_eligible
eligibility_reasons
```

PL confidence is no longer overwritten by a loose enrichment heuristic.
Discovery confidence is preserved and combined with independent profile/post
evidence.

Account types:

```text
person
creator_brand
media
company
```

Only `person` and `creator_brand` are included in the influencer ranking.
Media/company accounts remain in the normalized dataset and are exported under
`excluded_creators` in the web JSON instead of silently disappearing.

Eligibility also requires:
- public account,
- at least 10k followers,
- PL confidence >= 50,
- at least 5 measurable recent posts,
- recent activity within ~180 days.

Category matching now uses token/root boundaries, so short terms such as `ai`
no longer match inside unrelated words. `Other` is used when there is not
enough category evidence.

After uploading this patch, run:

```text
Actions → Rebuild InfluRank ranking
```

No Apify call is needed. The rebuild reclassifies all already stored creators,
updates `database/data/enriched_creators.json`, and regenerates the public
ranking.


## Autopilot

InfluRank can now run without manual GitHub clicks.

`InfluRank autopilot` has two schedules:

```text
Daily 04:17 UTC
- scans the next 2 discovery seeds
- advances a persistent seed cursor
- enriches up to 10 new pending creators
- recalculates the public ranking
- commits all updated data automatically

Sunday 04:47 UTC
- refreshes up to 25 oldest creator profiles
- stores a new follower snapshot
- keeps 30D momentum history growing
- recalculates the ranking
```

The discovery cursor lives in:

```text
database/data/pipeline_state.json
```

It wraps around the seed list automatically. If a provider run fails after only
one seed, only that completed seed is advanced; the failed seed is retried on
the next run.

Weekly refresh uses oldest-profile-first ordering so a fixed top-N group cannot
starve the rest of the dataset.

Manual `InfluRank discovery`, `InfluRank enrichment`, and
`Rebuild InfluRank ranking` workflows remain available as recovery/debug tools.


## Autopilot v2 — cost-aware bootstrap + steady state

Autopilot no longer loops blindly through a short seed list.

### Bootstrap

After upgrading the provider plan, use `mode=auto` or `mode=bootstrap`.

Defaults:

```text
20 search results per seed
max 25 discovery queries per run
bootstrap target: 250 eligible candidates
max 100 new profile enrichments per run
```

The seed universe has been expanded to 120+ Polish/category-specific queries.

The first bootstrap prefers:
1. seeds blocked earlier by Free-plan demo mode,
2. never-scanned seeds,
3. only then due re-scans.

### Steady state

Each seed stores:

```text
attempts
successful_scans
demo_only_count
provider_error_count
accepted_total
new_creators_total
last_new_rate
last_successful_at
next_due_at
```

Cooldown is based on yield:

```text
high yield        → ~14 days
medium yield      → ~30 days
one new creator   → ~60 days
zero new creators → ~90 days
no usable rows    → ~60 days
demo/provider cap → retry soon, NOT counted as successful
```

This means we do not keep paying for the same low-yield query every few days.

State:

```text
database/data/seed_state.json
```

### Profile refresh

Existing creators are only eligible for a scheduled refresh when their last
profile scan is at least 168 hours (7 days) old. The oldest profiles are
refreshed first.

This keeps follower snapshots growing while avoiding daily duplicate reads.

### Safety / scale checkpoint

The bootstrap target defaults to 250 candidates on purpose. At that point the
JSON/GitHub storage model and snapshot cadence should be reviewed before
pushing toward thousands of creators (e.g. move historical data to a database
and use lighter profile-only snapshot reads).


## Autopilot v2.1 — durable enrichment

Large enrichment batches no longer use Apify's synchronous
`run-sync-get-dataset-items` HTTP request.

The enrichment client now:
- starts Actor runs asynchronously,
- polls run status,
- fetches the completed dataset,
- uses batches of at most 50 handles,
- preserves successful batches if another batch fails.

Autopilot also commits a discovery checkpoint before enrichment. Therefore a
paid discovery run is not lost if profile enrichment later has a transient
network/provider failure.


## Autopilot v3 — self-expanding discovery graph

InfluRank no longer relies only on the hand-written seed list.

Every autopilot cycle learns from already accepted creators:

### Hashtag expansion

Recent posts from ranking-eligible creators are scanned for hashtags.

A specific hashtag is promoted to a new discovery seed when it has enough
evidence, especially when multiple eligible creators use it.

Generic tags such as:

```text
fyp
viral
tiktok
polska
polskatiktok
dlaciebie
```

are blocked from automatic promotion.

Dynamic seed metadata is stored in:

```text
database/data/dynamic_seed_meta.json
```

The discovery seed universe can grow automatically up to 500 dynamic seeds.
Only up to 25 new dynamic seeds are added in one harvest.

### Related creator expansion

@mentions in posts build a lightweight creator graph.

An unknown handle is promoted to profile enrichment only when:
- it is mentioned by at least two eligible creators, or
- it appears in at least two separate posts.

This avoids paying for every one-off mention.

State is stored in:

```text
database/data/related_handles.json
```

Up to 20 related handles are promoted per harvest.

### Autopilot cycle

```text
existing creators
      ↓
hashtags + mentions
      ↓
new dynamic seeds / related handles
      ↓
cost-aware discovery scheduler
      ↓
TikTok discovery
      ↓
new creators
      ↓
profile + post enrichment
      ↓
new hashtags + mentions
      ↓
next cycle becomes smarter
```

This is not ML; it is a controlled discovery graph with explicit cost caps and
quality thresholds. Static/category seeds remain as the stable foundation,
while the graph expands into topics and creator neighborhoods discovered in
real data.
