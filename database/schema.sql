PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS creators (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    handle TEXT NOT NULL UNIQUE,
    display_name TEXT,
    bio TEXT,
    avatar_url TEXT,
    verified INTEGER NOT NULL DEFAULT 0,
    pl_confidence REAL,
    category TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS creator_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    creator_id INTEGER NOT NULL,
    collected_at TEXT NOT NULL,
    followers INTEGER,
    following INTEGER,
    total_likes INTEGER,
    video_count INTEGER,
    FOREIGN KEY (creator_id) REFERENCES creators(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_snapshots_creator_time ON creator_snapshots(creator_id, collected_at DESC);

CREATE TABLE IF NOT EXISTS posts (
    id TEXT PRIMARY KEY,
    creator_id INTEGER NOT NULL,
    created_at TEXT,
    description TEXT,
    views INTEGER,
    likes INTEGER,
    comments INTEGER,
    shares INTEGER,
    collected_at TEXT NOT NULL,
    FOREIGN KEY (creator_id) REFERENCES creators(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_posts_creator_time ON posts(creator_id, created_at DESC);

CREATE TABLE IF NOT EXISTS discovery_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    source TEXT,
    status TEXT,
    discovered_handles INTEGER DEFAULT 0,
    scanned_profiles INTEGER DEFAULT 0,
    notes TEXT
);
