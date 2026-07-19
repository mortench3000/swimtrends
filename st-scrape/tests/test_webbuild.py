import json
from pathlib import Path

from webbuild import shape, queries
from tests.webbuild_fixtures import curated_con


def test_race_key_slug():
    assert shape.race_key("M", 100, "Fri", "LCM") == "M-100-Fri-LCM"


def test_write_json_roundtrip_keeps_danish(tmp_path: Path):
    p = tmp_path / "sub" / "x.json"
    shape.write_json(p, {"club": "Svømmeklubben Åræø"})
    text = p.read_text(encoding="utf-8")
    assert "Åræø" in text            # not \u-escaped
    assert json.loads(text)["club"] == "Svømmeklubben Åræø"


def test_fixture_has_views_and_two_seasons():
    con = curated_con()
    seasons = [r[0] for r in con.execute(
        "SELECT DISTINCT season FROM results_by_category "
        "WHERE category='DM-L' ORDER BY season").fetchall()]
    assert seasons == [2025, 2026]


def test_build_index_lists_category_and_seasons():
    idx = queries.build_index(curated_con())
    assert idx["attribution"] == "Data fra svømmetider.dk"
    dm_l = [c for c in idx["categories"] if c["code"] == "DM-L"][0]
    assert dm_l["seasons"] == [2026, 2025]      # newest first


def test_build_meets_lists_meets_newest_first():
    out = queries.build_meets(curated_con(), "DM-L")
    assert out["category"] == "DM-L"
    seasons = [m["season"] for m in out["meets"]]
    assert seasons == [2026, 2025]
    m = out["meets"][0]
    assert m["meet_id"] == "M2026"
    assert m["events"] == 2                 # 100 Fri + 200 Ryg
    assert m["entrants"] == 22              # 11 distinct swimmers/event x 2
    assert m["clubs"] >= 3
