-- M-CANDIDATES: review state and durable scoped material decisions; additive migration.
ALTER TABLE candidates ADD COLUMN state text NOT NULL DEFAULT 'pending'
    CHECK (state IN ('pending', 'accepted', 'rejected'));
ALTER TABLE candidates ADD COLUMN item_key text REFERENCES items(key);
ALTER TABLE candidates ADD COLUMN revision integer NOT NULL DEFAULT 0;
ALTER TABLE candidates ADD COLUMN reviewed_by text;
ALTER TABLE candidates ADD COLUMN reviewed_at timestamptz;
ALTER TABLE candidates ADD COLUMN review_note text NOT NULL DEFAULT '';
ALTER TABLE candidates ADD COLUMN draft jsonb NOT NULL DEFAULT '{}';
CREATE TABLE candidate_materials (
    candidate_id bigint NOT NULL REFERENCES candidates(id),
    material_id text NOT NULL REFERENCES materials(id),
    evidence jsonb NOT NULL DEFAULT '{}',
    suggestion text NOT NULL,
    decision text NOT NULL DEFAULT 'pending' CHECK (decision IN ('pending','included','excluded')),
    reviewed_by text,
    reviewed_at timestamptz,
    PRIMARY KEY(candidate_id, material_id)
);
INSERT INTO candidate_materials(candidate_id,material_id,evidence,suggestion)
SELECT id,material_id,proposal,'Исходный материал предложения' FROM candidates;
