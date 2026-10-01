# InfluRank Autopilot v4

Consolidated patch for `main`.

## What changed

- Keeps bootstrap target at 1000 and daily cost-aware discovery.
- Keeps graph expansion (dynamic hashtags + related creators).
- Keeps GEO collection and MAIN -> DEV `creators.json` sync.
- **Classifier v6:** stronger company/media filtering. TikTok `isOrganization`
  and seller signals now exclude obvious corporate accounts; brand-style
  national accounts such as `Starbucks Polska` are also caught while phrases
  like `Jones w Polsce` are not treated as corporate solely because of Poland.
- **GEO v2:** normalizes locality labels and rejects venue/service-area POIs
  such as `MOR ...` instead of publishing them as cities. `Gmina X` is reduced
  to `X`.
- **Quality report:** every run writes `database/data/quality_report.json` with
  ranking/exclusion counts, GEO coverage and a short list of suspicious
  business-like profiles that still passed the ranking.
- Discovery checkpoint now also commits dynamic seed/related-handle state so
  graph-learning is not lost if enrichment fails later in the run.
- Public ranking source label becomes `influRank-enrichment-v6`.

## Upload

Upload the contents of this ZIP to the **main** branch and commit directly to
`main`. Files replace the existing workflow/classifier/GEO files.

Then run **InfluRank autopilot v4** manually once with:

- mode: `auto`
- max paid queries: `25`
- bootstrap target: `1000`
- new profiles: `100`
- existing refresh: `100`

After a successful run:

1. `main` contains the new cleaned `creators.json`.
2. `dev` receives only `apps/web/data/creators.json` automatically.
3. Netlify refreshes `dev--rankinginflu.netlify.app`.
4. Check `database/data/quality_report.json` for quality diagnostics.
