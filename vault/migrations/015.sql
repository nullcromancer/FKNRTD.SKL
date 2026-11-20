CREATE TABLE IF NOT EXISTS scan_runs (
 id TEXT PRIMARY KEY,
 agent TEXT,
 model TEXT,
 state TEXT NOT NULL DEFAULT 'active' CHECK(state IN ('active','complete','interrupted')),
 started TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 finished TEXT
);
ALTER TABLE photos ADD COLUMN scan_run_id TEXT REFERENCES scan_runs(id);
CREATE INDEX IF NOT EXISTS photos_scan_run ON photos(scan_run_id,id);
