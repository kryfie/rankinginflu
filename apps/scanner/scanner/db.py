from pathlib import Path
import sqlite3
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[3]
DEFAULT_DB=ROOT/'apps'/'scanner'/'data'/'influrank.db'
SCHEMA=ROOT/'database'/'schema.sql'

def utcnow(): return datetime.now(timezone.utc).isoformat()

def connect(path=DEFAULT_DB):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    conn=sqlite3.connect(path); conn.execute('PRAGMA foreign_keys = ON')
    conn.executescript(SCHEMA.read_text(encoding='utf-8')); return conn

def save_snapshot(conn, creator, pl_confidence=None, category=''):
    now=creator.collected_at or utcnow(); handle=creator.handle.lstrip('@').lower()
    conn.execute("""
      INSERT INTO creators(handle,display_name,bio,avatar_url,verified,pl_confidence,category,first_seen_at,last_seen_at)
      VALUES(?,?,?,?,?,?,?,?,?)
      ON CONFLICT(handle) DO UPDATE SET display_name=excluded.display_name,bio=excluded.bio,avatar_url=excluded.avatar_url,verified=excluded.verified,pl_confidence=COALESCE(excluded.pl_confidence,creators.pl_confidence),category=CASE WHEN excluded.category<>'' THEN excluded.category ELSE creators.category END,last_seen_at=excluded.last_seen_at
    """,(handle,creator.display_name,creator.bio,creator.avatar_url,int(creator.verified),pl_confidence,category,now,now))
    cid=conn.execute('SELECT id FROM creators WHERE handle=?',(handle,)).fetchone()[0]
    conn.execute('INSERT INTO creator_snapshots(creator_id,collected_at,followers,following,total_likes,video_count) VALUES(?,?,?,?,?,?)',(cid,now,creator.followers,creator.following,creator.total_likes,creator.video_count))
    for p in creator.posts:
        conn.execute("""INSERT INTO posts(id,creator_id,created_at,description,views,likes,comments,shares,collected_at) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET views=excluded.views,likes=excluded.likes,comments=excluded.comments,shares=excluded.shares,description=excluded.description,collected_at=excluded.collected_at""",(p.post_id,cid,p.created_at,p.description,p.views,p.likes,p.comments,p.shares,now))
    conn.commit(); return cid
