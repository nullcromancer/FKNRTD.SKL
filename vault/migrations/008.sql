CREATE TABLE IF NOT EXISTS import_audit_origins (
 origin TEXT NOT NULL,
 source_audit_id INTEGER NOT NULL,
 local_audit_id INTEGER NOT NULL,
 PRIMARY KEY(origin,source_audit_id),
 UNIQUE(local_audit_id)
);
