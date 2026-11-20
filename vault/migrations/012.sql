DROP VIEW IF EXISTS current_inventory;
CREATE VIEW current_inventory AS
 SELECT i.*, v.estimate_cents,v.low_cents,v.high_cents,v.speculative_cents,v.source_url,v.basis,
 v.confidence AS valuation_confidence,v.methodology,v.rationale,
 (SELECT count(*) FROM valuation_comparables c WHERE c.valuation_id=v.id) AS comparable_count
 FROM items i LEFT JOIN valuations v ON v.id=(SELECT z.id FROM valuations z WHERE z.item_id=i.id ORDER BY z.rowid DESC LIMIT 1)
 WHERE i.active=1;
DROP VIEW IF EXISTS v_current_valuations;
CREATE VIEW v_current_valuations AS
 SELECT i.id AS item_id,v.id AS valuation_id,v.estimate_cents,v.low_cents,v.high_cents,v.speculative_cents,v.source_url,v.basis,v.confidence,v.created,v.methodology,v.rationale,
 (SELECT count(*) FROM valuation_comparables c WHERE c.valuation_id=v.id) AS comparable_count
 FROM items i LEFT JOIN valuations v ON v.id=(SELECT x.id FROM valuations x WHERE x.item_id=i.id ORDER BY x.rowid DESC LIMIT 1)
 WHERE i.active=1;
