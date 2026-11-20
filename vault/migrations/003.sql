ALTER TABLE archive_members RENAME TO archive_members_old;
ALTER TABLE archives ADD COLUMN destination TEXT;
CREATE TABLE archive_members (
 id TEXT PRIMARY KEY, archive_id TEXT NOT NULL REFERENCES archives(id), member_name TEXT NOT NULL,
 member_index INTEGER NOT NULL DEFAULT 0, extracted_path TEXT, sha256 TEXT,
 disposition TEXT NOT NULL DEFAULT 'pending', photo_id TEXT REFERENCES photos(id), error TEXT,
 UNIQUE(archive_id,member_name,member_index)
);
INSERT INTO archive_members(id,archive_id,member_name,member_index,extracted_path,sha256,disposition,photo_id,error)
 SELECT id,archive_id,member_name,0,extracted_path,sha256,disposition,photo_id,error FROM archive_members_old;
DROP TABLE archive_members_old;
CREATE INDEX IF NOT EXISTS archive_members_disposition ON archive_members(archive_id,disposition);
