CREATE TABLE IF NOT EXISTS import_comparable_origins (
 origin TEXT NOT NULL,
 source_id TEXT NOT NULL,
 local_id TEXT NOT NULL,
 PRIMARY KEY(origin,source_id),
 UNIQUE(local_id)
);
