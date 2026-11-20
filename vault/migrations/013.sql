CREATE TABLE IF NOT EXISTS detail_assets (
 id TEXT PRIMARY KEY,
 observation_id TEXT NOT NULL REFERENCES observations(id) ON DELETE CASCADE,
 frame INTEGER NOT NULL CHECK(frame>=0),
 box TEXT NOT NULL,
 path TEXT NOT NULL,
 label TEXT NOT NULL,
 sha256 TEXT NOT NULL CHECK(length(sha256)=64),
 bytes INTEGER NOT NULL CHECK(bytes>=0),
 created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS detail_assets_observation ON detail_assets(observation_id,created);
