InfluRank GEO v1

Purpose
-------
Start collecting city/location evidence now, without making it a ranking
eligibility requirement and without adding extra paid provider calls.

Sources used:
1. TikTok POI metadata already returned by discovery.
2. City explicitly present in a creator bio.
3. Repeated city mentions in post captions / hashtags.
4. City mentions in discovery post text.

The system does NOT guess a city when evidence is weak.

Stored fields
-------------
database/data/geo_evidence.json
  Persistent, deduplicated evidence events across autopilot runs.

database/data/enriched_creators.json
  Adds:
  - geo
  - primary_city
  - home_city
  - geo_confidence

apps/web/data/creators.json
  Adds:
  - city
  - home_city
  - geo_confidence
  - geo_sources
  - content_cities

Interpretation
--------------
home_city:
  Only set from strong bio evidence. It is still a public-profile inference,
  not a private address.

city / primary_city:
  Best public location association. It may reflect where the creator creates
  content, not where they live.

The current public frontend does not need to show city yet. We can first
measure coverage and accuracy, then add a city filter once the signal is useful.

Workflow
--------
Autopilot runs geo harvest after enrichment/refresh, so no new Apify query is
needed solely for city collection.

Upload this overlay to the same branch as Autopilot v3 (main). It replaces
autopilot.yml and rebuild-ranking.yml and adds the geo module/state/test.


GEO v1.1 correction
-------------------
Validated against a real InfluRank provider artifact from 2026-10-01.
The discovery provider often returns numeric regionCode values and leaves
cityName blank even when poiName/address clearly contain a Polish city.
v1.1 parses cityName + address + poiName, rejects conflicting POI metadata,
and recovers locations such as Szczecin/Bydgoszcz/Przysucha without extra
provider calls.


GEO v1.2 workflow fix
---------------------
The manual `Rebuild InfluRank ranking` workflow now runs GEO harvest after
reclassifying/rebuilding the ranking, so a manual rebuild does not temporarily
remove city fields from creators.json.
