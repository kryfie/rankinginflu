# Changelog

## 2026-10-01 — Discovery v2
- real per-seed discovery (one provider run per seed),
- `results_per_seed` replaces misleading global `max_items`,
- persistent candidate registry (upsert, no one-run overwrite),
- persistent scanner queue statuses,
- compact Git-tracked raw data,
- full provider payload moved to short-lived Actions artifact,
- production discovery restricted to `main`,
- provider `verified` explicitly diagnostic only,
- public profile workflow simplified to profile-first mode,
- fixed `slardarwaf` profile-page false positive,
- added discovery unit tests.
