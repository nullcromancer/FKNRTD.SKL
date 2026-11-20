CREATE TABLE IF NOT EXISTS import_entity_origins (
 origin TEXT NOT NULL,
 entity_type TEXT NOT NULL CHECK(entity_type IN ('item','photo','observation','evidence','valuation')),
 source_id TEXT NOT NULL,
 local_id TEXT NOT NULL,
 PRIMARY KEY(origin,entity_type,source_id),
 UNIQUE(entity_type,local_id)
);
