CREATE TABLE IF NOT EXISTS photos (
 id TEXT PRIMARY KEY, source TEXT NOT NULL, sha256 TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('claimed','committed_pending_move','archived','failed_pending_move','failed_archived')),
 destination TEXT NOT NULL, error TEXT, width INTEGER, height INTEGER, frame_count INTEGER, claim_token TEXT NOT NULL, created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS photos_hash ON photos(sha256,state);
CREATE UNIQUE INDEX IF NOT EXISTS photos_active_source ON photos(source) WHERE state IN ('claimed','committed_pending_move','failed_pending_move');
CREATE TABLE IF NOT EXISTS products (id TEXT PRIMARY KEY, identity_key TEXT UNIQUE NOT NULL, name TEXT NOT NULL, metadata TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS items (
 id TEXT PRIMARY KEY, product_id TEXT REFERENCES products(id), name TEXT NOT NULL, category TEXT NOT NULL, type TEXT NOT NULL, subtype TEXT, confidence REAL NOT NULL CHECK(confidence BETWEEN 0 AND 100),
 condition TEXT, condition_confidence REAL CHECK(condition_confidence BETWEEN 0 AND 100), metadata TEXT NOT NULL DEFAULT '{}', primary_image TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
 review INTEGER NOT NULL DEFAULT 0, pending_research INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS observations (id TEXT PRIMARY KEY, photo_id TEXT NOT NULL REFERENCES photos(id), item_id TEXT NOT NULL REFERENCES items(id), frame INTEGER NOT NULL DEFAULT 0, box TEXT NOT NULL, image TEXT NOT NULL, association TEXT NOT NULL, duplicate_confidence REAL, notes TEXT, UNIQUE(photo_id,item_id));
CREATE TABLE IF NOT EXISTS evidence (id TEXT PRIMARY KEY,item_id TEXT NOT NULL REFERENCES items(id),observation_id TEXT REFERENCES observations(id),url TEXT NOT NULL,kind TEXT NOT NULL, description TEXT, observed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS valuations (id TEXT PRIMARY KEY,item_id TEXT NOT NULL REFERENCES items(id),observation_id TEXT REFERENCES observations(id), estimate_cents INTEGER, low_cents INTEGER, high_cents INTEGER,speculative_cents INTEGER,source_url TEXT,basis TEXT NOT NULL,confidence REAL CHECK(confidence BETWEEN 0 AND 100),created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, item_id TEXT REFERENCES items(id),photo_id TEXT REFERENCES photos(id),action TEXT NOT NULL,detail TEXT NOT NULL,created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS asset_journal (photo_id TEXT NOT NULL REFERENCES photos(id),path TEXT NOT NULL PRIMARY KEY);
CREATE VIEW IF NOT EXISTS current_inventory AS SELECT i.*, v.estimate_cents,v.low_cents,v.high_cents,v.speculative_cents,v.source_url,v.basis,v.confidence AS valuation_confidence FROM items i LEFT JOIN valuations v ON v.id=(SELECT z.id FROM valuations z WHERE z.item_id=i.id ORDER BY z.rowid DESC LIMIT 1) WHERE i.active=1;
