"""Curated-zone data-overview queries (swimtrends meets / categories / summary).

Counts come straight off cur_obt/cur_dim_meet (no views needed): races =
distinct race_id, results = row count, dsq = rank -1. A meet tagged with N
categories contributes to each in `categories` (per-category totals), same as
results_by_category.
"""
import duckdb

from analytics import overview
from tests.analytics_fixtures import build_curated

BASE = dict(nationality="DK", club="C", birth_year=2005, relay_count=1,
            gender="M", distance=100, stroke="Fri", course="LCM",
            completed_time="t", completed_centiseconds=6000, type="Heats")


def _obt(rid, meet, race, rank, swimmer, season):
    r = dict(BASE)
    r.update(result_id=rid, meet_id=meet, race_id=race, rank=rank,
             swimmer_id=swimmer, name=swimmer, season=season)
    r["class"] = "open"
    return r


MEETS = [
    dict(meet_id="m1", meet_name="DM Langbane 2024", venue="Bellahøj", course="LCM",
         season=2024, meet_date="11-07-2024", category=["DM-L"]),
    dict(meet_id="m2", meet_name="DM Kortbane 2020", venue="Esbjerg", course="SCM",
         season=2021, meet_date="14-12-2020", category=["DM-K"]),
]
OBT = [
    _obt("r1", "m1", 10, 1, "s1", 2024),
    _obt("r2", "m1", 10, 2, "s2", 2024),
    _obt("r3", "m1", 11, -1, "s3", 2024),   # DSQ, its own race
    _obt("r4", "m2", 20, 1, "s4", 2021),
    _obt("r5", "m2", 20, 2, "s5", 2021),
]


def _con(meets=MEETS, obt=OBT):
    con = duckdb.connect()
    build_curated(con, obt=obt, meets=meets)
    return con


def test_list_meets_sorted_by_season_with_counts():
    rows = overview.list_meets(_con())
    assert [r["season"] for r in rows] == [2021, 2024]      # season order
    m1 = next(r for r in rows if r["meet_id"] == "m1")
    assert (m1["races"], m1["results"], m1["dsq"]) == (2, 3, 1)
    assert m1["venue"] == "Bellahøj"
    m2 = next(r for r in rows if r["meet_id"] == "m2")
    assert (m2["races"], m2["results"], m2["dsq"]) == (1, 2, 0)


def test_list_meets_filters_by_category_and_season():
    assert [r["meet_id"] for r in overview.list_meets(_con(), category="DM-K")] == ["m2"]
    assert [r["meet_id"] for r in overview.list_meets(_con(), season=2024)] == ["m1"]


def test_list_categories_coverage():
    rows = {r["category"]: r for r in overview.list_categories(_con())}
    assert rows["DM-K"]["meets"] == 1
    assert (rows["DM-L"]["season_min"], rows["DM-L"]["season_max"]) == (2024, 2024)
    assert rows["DM-L"]["results"] == 3


def test_summary_totals():
    s = overview.summary(_con())
    assert s["meets"] == 2
    assert s["results"] == 5
    assert s["swimmers"] == 5
    assert (s["season_min"], s["season_max"]) == (2021, 2024)
    assert s["categories"] == ["DM-K", "DM-L"]


def test_render_table_aligns_columns():
    out = overview.render_table(["a", "bb"], [[1, "x"], [22, "yy"]])
    lines = out.splitlines()
    assert lines[0].split() == ["a", "bb"]
    # every data cell present; columns padded to a consistent width
    assert "22" in lines[-1] and "yy" in lines[-1]
    assert len({len(l) for l in lines}) == 1  # all rows same rendered width
