InfluRank Autopilot v4.1 — enrichment compatibility fix

Problem:
current apps/enrichment/cli.py calls select_queue_items(...,
min_refresh_age_hours=...), but Autopilot v4 shipped an older pipeline
function signature. GitHub Actions therefore failed before calling Apify
with:
  TypeError: select_queue_items() got an unexpected keyword argument
  'min_refresh_age_hours'

Fix:
- accepts min_refresh_age_hours,
- normal enrichment still selects pending/error accounts,
- 7-day refresh selects only status=enriched profiles older than 168h,
- missing legacy refresh timestamp is treated as due once,
- no workflow changes are required.

Upload this overlay to branch main, preserving folders, then rerun
"InfluRank autopilot v4".
