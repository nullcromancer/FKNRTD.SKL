CREATE TABLE IF NOT EXISTS merge_members (
 merge_id TEXT NOT NULL, entity_type TEXT NOT NULL CHECK(entity_type IN ('observation','evidence','valuation')),
 entity_id TEXT NOT NULL, source_id TEXT NOT NULL, target_id TEXT NOT NULL,
 PRIMARY KEY(merge_id,entity_type,entity_id)
);
CREATE VIEW IF NOT EXISTS v_current_valuations AS
 SELECT i.id AS item_id,v.estimate_cents,v.low_cents,v.high_cents,v.speculative_cents,v.source_url,v.basis,v.confidence,v.created
 FROM items i LEFT JOIN valuations v ON v.id=(SELECT x.id FROM valuations x WHERE x.item_id=i.id ORDER BY x.rowid DESC LIMIT 1)
 WHERE i.active=1;
CREATE VIEW IF NOT EXISTS v_item_sources AS
 SELECT o.item_id,p.id AS photo_id,p.source,p.destination,o.frame,o.box,o.image,o.association
 FROM observations o JOIN photos p ON p.id=o.photo_id;
CREATE VIEW IF NOT EXISTS v_review_queue AS
 SELECT id AS item_id,name,category,type,confidence,review,pending_research FROM items WHERE active=1 AND (review=1 OR pending_research=1);
CREATE VIEW IF NOT EXISTS v_catalog_totals AS
 SELECT count(*) AS active_items,
 sum(CASE WHEN v.estimate_cents IS NOT NULL THEN v.estimate_cents ELSE 0 END) AS evidence_value_cents,
 sum(CASE WHEN v.estimate_cents IS NULL THEN coalesce(v.speculative_cents,0) ELSE 0 END) AS speculative_unvalued_cents,
 sum(CASE WHEN v.estimate_cents IS NULL AND v.speculative_cents IS NULL THEN 1 ELSE 0 END) AS unvalued_items
 FROM items i LEFT JOIN v_current_valuations v ON v.item_id=i.id WHERE i.active=1;
CREATE VIEW IF NOT EXISTS v_inventory AS
 SELECT i.id AS item_id,i.name AS item_name,i.type AS item_type,
 (SELECT p.source FROM observations o JOIN photos p ON p.id=o.photo_id WHERE o.item_id=i.id ORDER BY o.rowid LIMIT 1) AS source_image_name,
 v.estimate_cents AS approximate_value_cents,v.source_url AS value_url,i.confidence,i.primary_image AS crop_path,
 v.low_cents,v.high_cents,v.basis AS valuation_basis,i.review AS review_flag,i.pending_research
 FROM items i LEFT JOIN v_current_valuations v ON v.item_id=i.id WHERE i.active=1;
