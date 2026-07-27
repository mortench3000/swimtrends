from tests.evaluation_fixtures import digest_con, junior_digest_con
from webbuild import digest


def test_meet_header():
    d = digest.build(digest_con(), "DM-L", "D2026")
    assert d["meet"] == {"name": "Danish Champs 2026", "date": "2026-04-10",
                         "season": 2026, "category": "DM-L", "course": "LCM"}


def test_facts_are_present_and_scored():
    d = digest.build(digest_con(), "DM-L", "D2026")
    f = d["facts"]
    assert f["entrants"] == 24            # 4 events x 6 swimmers
    assert f["events"] == 4
    assert f["clubs"] == 3
    assert f["top_points"] == 653         # 400 + 20*5 + 5*30 + 3 (last event)
    assert f["median_points"] == 576      # 24 swims; quantile_cont(0.5) of 563,590 -> 576
    assert f["elite_median_points"] == 576


def test_season_history_is_newest_first_and_capped_at_six_rows():
    # the meet's own season plus the five prior seasons on record
    d = digest.build(digest_con(), "DM-L", "D2026")
    seasons = [r["season"] for r in d["season_history"]]
    assert seasons == [2026, 2025, 2024, 2023, 2022, 2021]


def test_season_history_truncates_to_the_window_for_an_older_meet():
    d = digest.build(digest_con(), "DM-L", "D2023")
    seasons = [r["season"] for r in d["season_history"]]
    assert seasons == [2023, 2022, 2021]          # nothing before 2021 exists
    assert all(s <= 2023 for s in seasons)        # never looks into the future


def test_junior_scoped_meet_uses_the_junior_championship():
    d = digest.build(junior_digest_con(), "DMJ-L", "J2026")
    assert d["meet"]["category"] == "DMJ-L"
    assert d["facts"]["entrants"] == 4             # the four juniors, not the seniors


def test_junior_scoping_follows_any_senior_plus_junior_tag_pair():
    """A DO+DMJ-L meet is junior-scoped on the meet page (queries._meet_is_combined),
    so the digest must scope it the same way — otherwise the evaluation describes a
    different field than the page shows."""
    con = junior_digest_con()
    con.execute("UPDATE cur_dim_meet SET category = ['DO', 'DMJ-L'] WHERE meet_id = 'J2026'")
    d = digest.build(con, "DMJ-L", "J2026")
    assert d["facts"]["entrants"] == 4        # the four juniors, not the seniors


def test_top_swims_are_points_descending_and_capped():
    d = digest.build(digest_con(), "DM-L", "D2026")
    pts = [s["points"] for s in d["top_swims"]]
    assert len(pts) == 10
    assert pts == sorted(pts, reverse=True)
    top = d["top_swims"][0]
    assert set(top) == {"name", "club", "event", "time", "points", "rank"}
    assert top["event"] == "F 200m Bryst (LCM)"   # highest-scoring event in the fixture


def test_top_swims_dedupe_a_swimmer_within_an_event():
    # the junior fixture has the same swimmer in heats AND final of M 100 Fri
    d = digest.build(junior_digest_con(), "DM-L", "J2026")
    names = [s["name"] for s in d["top_swims"]]
    assert len(names) == len(set(names))


def test_by_stroke_has_a_row_per_stroke_and_distance_group():
    d = digest.build(digest_con(), "DM-L", "D2026")
    keys = {(r["stroke"], r["dist_group"]) for r in d["by_stroke"]}
    assert keys == {("Fri", "sprint"), ("Fri", "lang"),
                    ("Ryg", "middel"), ("Bryst", "middel")}
    row = next(r for r in d["by_stroke"] if r["stroke"] == "Ryg")
    assert row["median_points"] > row["prev5_median"]   # points climb with season


def test_by_stroke_prev5_is_null_when_there_is_no_history():
    d = digest.build(digest_con(), "DM-L", "D2021")
    assert all(r["prev5_median"] is None for r in d["by_stroke"])


def test_derived_holds_rounded_percentage_deltas():
    d = digest.build(digest_con(), "DM-L", "D2026")
    assert "median_points_vs_prev5_pct" in d["derived"]
    assert "entrants_vs_prev5_pct" in d["derived"]
    assert all(isinstance(v, int) for v in d["derived"].values())


def test_derived_is_empty_for_a_meet_with_no_prior_seasons():
    d = digest.build(digest_con(), "DM-L", "D2021")
    assert d["derived"] == {}
