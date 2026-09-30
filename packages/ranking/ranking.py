from statistics import median, pstdev, mean
from math import log10
from datetime import datetime
import sqlite3

WEIGHTS = {"reach":0.30,"engagement":0.25,"audience":0.20,"momentum":0.15,"consistency":0.10}

def _percentile(values, value):
    vals = sorted(v for v in values if v is not None)
    if not vals: return 50.0
    if len(vals) == 1: return 50.0
    below = sum(1 for v in vals if v < value)
    equal = sum(1 for v in vals if v == value)
    return 100.0 * (below + 0.5 * equal) / len(vals)

def _latest_rows(conn: sqlite3.Connection):
    conn.row_factory = sqlite3.Row
    return conn.execute("""
      SELECT c.*, s.followers, s.following, s.total_likes, s.video_count, s.collected_at
      FROM creators c
      JOIN creator_snapshots s ON s.id = (
        SELECT s2.id FROM creator_snapshots s2
        WHERE s2.creator_id = c.id ORDER BY s2.collected_at DESC LIMIT 1
      )
    """).fetchall()

def build_ranking(conn: sqlite3.Connection):
    rows = _latest_rows(conn)
    raw = []
    for row in rows:
        posts = conn.execute("""
          SELECT views, likes, comments, shares, created_at FROM posts
          WHERE creator_id=? ORDER BY COALESCE(created_at, collected_at) DESC LIMIT 30
        """, (row['id'],)).fetchall()
        views = [max(0,int(p[0] or 0)) for p in posts if int(p[0] or 0)>0]
        engagements = [100.0*(int(p[1] or 0)+int(p[2] or 0)+int(p[3] or 0))/max(1,int(p[0] or 0)) for p in posts if int(p[0] or 0)>0]
        median_views = float(median(views)) if views else 0.0
        engagement = float(median(engagements)) if engagements else 0.0
        followers = int(row['followers'] or 0)
        reach_ratio = median_views/max(1,followers)
        if len(views)>=3 and mean(views)>0:
            cv=pstdev(views)/mean(views); consistency=max(0.0,min(100.0,100.0*(1.0-min(cv,1.0))))
        else: consistency=50.0
        latest_dt=datetime.fromisoformat(str(row['collected_at']).replace('Z','+00:00'))
        target=latest_dt.timestamp()-30*86400
        older=None
        for h in conn.execute("SELECT followers,collected_at FROM creator_snapshots WHERE creator_id=? ORDER BY collected_at ASC",(row['id'],)).fetchall():
            try:
                if datetime.fromisoformat(str(h[1]).replace('Z','+00:00')).timestamp()<=target: older=h
            except Exception: pass
        growth=None
        if older and int(older[0] or 0)>0: growth=100.0*(followers-int(older[0]))/int(older[0])
        raw.append({"handle":row['handle'],"name":row['display_name'] or row['handle'],"avatar":row['avatar_url'] or "","verified":bool(row['verified']),"category":row['category'] or "","pl_confidence":row['pl_confidence'],"followers":followers,"views":median_views,"engagement":engagement,"growth":growth,"reach_ratio":reach_ratio,"consistency_raw":consistency,"updated_at":row['collected_at']})
    if not raw: return []
    audience_vals=[log10(max(1,x['followers'])) for x in raw]
    reach_vals=[x['reach_ratio'] for x in raw]
    engagement_vals=[x['engagement'] for x in raw]
    growth_vals=[x['growth'] for x in raw if x['growth'] is not None]
    for x in raw:
        comp={"audience":_percentile(audience_vals,log10(max(1,x['followers']))),"reach":_percentile(reach_vals,x['reach_ratio']),"engagement":_percentile(engagement_vals,x['engagement']),"momentum":_percentile(growth_vals,x['growth']) if x['growth'] is not None else 50.0,"consistency":x['consistency_raw']}
        x['score']=round(sum(comp[k]*WEIGHTS[k] for k in WEIGHTS),1)
        x['components']={k:round(v,1) for k,v in comp.items()}
        if x['growth'] is None: x['growth']=0.0
        x.pop('reach_ratio',None); x.pop('consistency_raw',None)
    raw.sort(key=lambda x:x['score'],reverse=True)
    for i,x in enumerate(raw,1): x['rank']=i
    return raw
