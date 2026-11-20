CREATE TABLE IF NOT EXISTS valuation_comparables (
 id TEXT PRIMARY KEY,
 valuation_id TEXT NOT NULL REFERENCES valuations(id),
 item_id TEXT NOT NULL REFERENCES items(id),
 source_url TEXT NOT NULL,
 sale_basis TEXT NOT NULL CHECK(sale_basis IN ('sold','dealer','asking','retail')),
 original_amount TEXT NOT NULL,
 currency TEXT NOT NULL CHECK(length(currency)=3),
 quantity INTEGER NOT NULL DEFAULT 1 CHECK(quantity>0),
 sold_at TEXT,
 fx_rate TEXT,
 fx_source_url TEXT,
 normalized_unit_cents INTEGER NOT NULL CHECK(normalized_unit_cents>=0),
 adjusted_unit_cents INTEGER NOT NULL CHECK(adjusted_unit_cents>=0),
 adjustment_notes TEXT NOT NULL DEFAULT '',
 observed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS valuation_comparables_item ON valuation_comparables(item_id,sold_at);
