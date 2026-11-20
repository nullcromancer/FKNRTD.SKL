ALTER TABLE photos ADD COLUMN perceptual_hash TEXT;
CREATE INDEX IF NOT EXISTS photos_perceptual_hash ON photos(perceptual_hash,state);
