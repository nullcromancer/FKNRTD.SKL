CREATE TABLE IF NOT EXISTS taxonomy_nodes (
 id TEXT PRIMARY KEY,
 kind TEXT NOT NULL CHECK(kind IN ('category','type','subtype')),
 parent_id TEXT REFERENCES taxonomy_nodes(id),
 parent_key TEXT NOT NULL DEFAULT '',
 name TEXT NOT NULL,
 slug TEXT NOT NULL,
 created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(kind,parent_key,slug)
);
CREATE TABLE IF NOT EXISTS taxonomy_aliases (
 id INTEGER PRIMARY KEY,
 kind TEXT NOT NULL CHECK(kind IN ('category','type','subtype')),
 parent_key TEXT NOT NULL DEFAULT '',
 alias_key TEXT NOT NULL,
 node_id TEXT NOT NULL REFERENCES taxonomy_nodes(id),
 alias TEXT NOT NULL,
 UNIQUE(kind,parent_key,alias_key)
);
CREATE TABLE IF NOT EXISTS item_taxonomy (
 item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
 kind TEXT NOT NULL CHECK(kind IN ('category','type','subtype')),
 node_id TEXT NOT NULL REFERENCES taxonomy_nodes(id),
 PRIMARY KEY(item_id,kind)
);
CREATE INDEX IF NOT EXISTS taxonomy_parent ON taxonomy_nodes(kind,parent_key);
CREATE INDEX IF NOT EXISTS taxonomy_alias_lookup ON taxonomy_aliases(kind,parent_key,alias_key);
CREATE INDEX IF NOT EXISTS item_taxonomy_node ON item_taxonomy(node_id,item_id);
