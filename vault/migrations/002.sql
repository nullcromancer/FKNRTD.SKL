CREATE TABLE IF NOT EXISTS archives (
 id TEXT PRIMARY KEY, source TEXT NOT NULL, sha256 TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('extracting','members_pending','archived','rejected')),
 error TEXT, created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS archive_members (
 id TEXT PRIMARY KEY, archive_id TEXT NOT NULL REFERENCES archives(id), member_name TEXT NOT NULL, member_index INTEGER NOT NULL DEFAULT 0,
 extracted_path TEXT, sha256 TEXT, disposition TEXT NOT NULL DEFAULT 'pending',
 photo_id TEXT REFERENCES photos(id), error TEXT, UNIQUE(archive_id,member_name,member_index)
);
CREATE INDEX IF NOT EXISTS archive_members_disposition ON archive_members(archive_id,disposition);
CREATE TABLE IF NOT EXISTS field_locks(item_id TEXT NOT NULL REFERENCES items(id),field TEXT NOT NULL,locked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,reason TEXT,PRIMARY KEY(item_id,field));
CREATE TABLE IF NOT EXISTS item_aliases(alias_id TEXT PRIMARY KEY,item_id TEXT NOT NULL REFERENCES items(id),reason TEXT NOT NULL,created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS catalog_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
INSERT OR IGNORE INTO catalog_meta(key,value) VALUES('catalog_uuid',lower(hex(randomblob(16))));
CREATE TABLE IF NOT EXISTS research_cache(cache_key TEXT PRIMARY KEY,result_json TEXT NOT NULL,source_urls TEXT NOT NULL,created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,expires TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS research_queue(item_id TEXT PRIMARY KEY REFERENCES items(id),status TEXT NOT NULL DEFAULT 'pending',attempts INTEGER NOT NULL DEFAULT 0,last_error TEXT,updated TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS research_runs(id TEXT PRIMARY KEY,item_id TEXT,query TEXT NOT NULL,source TEXT NOT NULL,visited_url TEXT,cache_hit INTEGER NOT NULL DEFAULT 0,created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS item_origins(origin TEXT NOT NULL,source_item_id TEXT NOT NULL,local_item_id TEXT NOT NULL REFERENCES items(id),PRIMARY KEY(origin,source_item_id));
