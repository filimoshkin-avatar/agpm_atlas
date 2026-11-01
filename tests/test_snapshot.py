import json

from atlas import importer, reconcile, snapshot
from atlas.importer import SEED


def _build(conn):
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    version, versions = snapshot.first_version(seed["version"], 794, 27)
    return snapshot.build(conn, version, versions)


def test_version_2026_10_09_matches_reference_and_prototype(empty_db, reference, prototype_data):
    importer.run(empty_db)
    snap = _build(empty_db)
    assert reconcile.against_reference(snap, reference) == []
    assert reconcile.against_prototype(snap, prototype_data) == []


def test_snapshot_is_stored_once_with_its_hash(empty_db):
    importer.run(empty_db)
    snap = _build(empty_db)
    digest = snapshot.store(empty_db, snap, state="current")
    row = empty_db.execute("SELECT snapshot, snapshot_sha256, state FROM versions").fetchone()
    assert row["snapshot_sha256"] == digest == snapshot.sha256(row["snapshot"])
    assert row["state"] == "current"


def test_reconcile_catches_a_changed_text(empty_db, reference, prototype_data):
    importer.run(empty_db)
    empty_db.execute("UPDATE materials SET summary = summary || ' ' WHERE num = 1")
    snap = _build(empty_db)
    assert any("№ 1: summary" in e for e in reconcile.against_reference(snap, reference))
    assert reconcile.against_prototype(snap, prototype_data)


def test_reconcile_catches_a_wrong_signal(empty_db, reference):
    importer.run(empty_db)
    empty_db.execute("UPDATE links SET counts = true WHERE material_id = 'm000117' AND item_key = 'B1_drafts'")
    snap = _build(empty_db)
    assert any("B1_drafts: правило даёт" in e for e in reconcile.against_reference(snap, reference))
