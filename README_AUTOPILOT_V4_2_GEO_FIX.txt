InfluRank Autopilot v4.2 — GEO false-positive fix

Why this patch exists
---------------------
A real example exposed a conceptual GEO bug:

  @kapitanburgerpolice
  creator/base: Police near Szczecin
  one TikTok post: food in/near Białystok
  TikTok POI: Białystok

The previous scoring gave one POI enough confidence to become the public
creator city, so the creator appeared under Białystok.

New rule
--------
TikTok POI means "where this post is associated", not "where the creator
is based".

A city is now promoted to the public city only when at least one of these
is true:
  - explicit bio city,
  - 2+ distinct posts with the same POI city,
  - POI + independent text evidence agree on the same city,
  - repeated textual city evidence across 4+ distinct posts.

A single POI remains available in content_cities, but public city=null.

Effect on the reported example
------------------------------
Białystok will no longer be the public city for @kapitanburgerpolice
solely because one post had a Białystok POI. Until stable evidence for
Police is collected, showing no city is safer than showing a wrong city.

This overlay also includes the v4.1 enrichment compatibility fix.

Upload to MAIN, preserving folders, then rerun InfluRank autopilot v4.
