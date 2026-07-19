import json
from pathlib import Path

from webbuild import shape
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
