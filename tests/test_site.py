import json
import re

import pytest

from atlas import importer, site, snapshot
from atlas.importer import SEED


@pytest.fixture
def built(empty_db, tmp_path):
    importer.run(empty_db)
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    version, versions = snapshot.first_version(seed["version"], 794, 27)
    snap = snapshot.build(empty_db, version, versions)
    out = tmp_path / "2026-10-09"
    return snap, out, site.build(snap, out)


def test_every_spec_route_is_a_real_page(built):
    snap, out, manifest = built
    expected = ["index.html", "index/index.html", "sections/index.html", "versions/index.html",
                "versions/2026-10-09/index.html", "method/index.html", "404.html", "robots.txt", "sitemap.xml"]
    expected += [f"scenario/{i['key']}/index.html" for i in snap["items"]]
    expected += [f"m/{m['num']}/index.html" for m in snap["materials"]]
    expected += [f"section/{s['key']}/index.html" for s in snap["refs"]["sections"]]
    expected += [f"section/practice/{p['key']}/index.html" for p in snap["refs"]["practices"]]
    missing = [p for p in expected if not (out / p).is_file()]
    assert missing == []
    assert manifest["pages"] == 1 + 27 + 1 + 794 + 1 + 9 + 16 + 1 + 1 + 1


def test_assets_and_data_carry_their_content_hash(built):
    _, out, manifest = built
    names = [n for n in manifest["files"] if n.startswith(("assets/atlas", "assets/fonts.", "data/"))]
    assert len(names) == 5
    for name in names:
        assert re.search(r"\.[0-9a-f]{12}\.(js|css|json)$", name), name
        digest = re.search(r"\.([0-9a-f]{12})\.", name).group(1)
        assert manifest["files"][name].startswith(digest), name


def test_pages_use_relative_links_so_one_folder_serves_root_and_snapshot(built):
    _, out, _ = built
    page = (out / "scenario" / "B1_drafts" / "index.html").read_text(encoding="utf-8")
    assert 'data-root="../../"' in page
    assert re.search(r'(href|src)="/(?!/)', page) is None
    assert "<title>Подсказки и черновики планов — Атлас AgPM</title>" in page
    assert 'rel="canonical" href="https://atlas.agpm.space/scenario/B1_drafts/"' in page


def test_public_bundle_has_no_demo_data_and_no_cabinet(built):
    _, out, manifest = built
    js = next(out / n for n in manifest["files"] if n.startswith("assets/atlas.") and n.endswith(".js"))
    text = js.read_text(encoding="utf-8")
    for needle in ("ATLAS_DEMO", "viewEditor", "atlas-editor", "#/"):
        assert needle not in text.split("\n", 3)[-1], needle
    assert not (out / "data" / "demo.js").exists()


def test_core_data_has_no_materials_and_sitemap_skips_snapshots(built):
    snap, out, manifest = built
    core = next(n for n in manifest["files"] if n.startswith("data/core."))
    data = json.loads((out / core).read_text(encoding="utf-8"))
    assert "materials" not in data and "links" not in data and data["computed"]["material_total"] == 794
    sitemap = (out / "sitemap.xml").read_text(encoding="utf-8")
    assert sitemap.count("<loc>") == manifest["pages"] and "/v/" not in sitemap
    assert "Disallow: /v/" in (out / "robots.txt").read_text(encoding="utf-8")


def test_built_version_folder_is_immutable(built):
    snap, out, _ = built
    with pytest.raises(FileExistsError):
        site.build(snap, out)


def test_stylesheets_have_balanced_braces():
    """Лишняя «}» молча выбрасывает следующее правило (так пропала закреплённая шапка)."""
    from atlas import ROOT
    for name in ("atlas.css", "fonts.css"):
        depth = 0
        text = (ROOT / "site" / "assets" / name).read_text(encoding="utf-8")
        import re
        for ch in re.sub(r"/\*.*?\*/", "", text, flags=re.S):
            depth += {"{": 1, "}": -1}.get(ch, 0)
            assert depth >= 0, f"{name}: лишняя «}}»"
        assert depth == 0, f"{name}: незакрытая «{{»"
