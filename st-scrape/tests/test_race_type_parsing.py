"""Race-type parsing: 'Direkte finale' must be preserved as a distinct type.

The site labels a final swum without prelims as 'Direkte finale'. At these meets
the para events appear as exactly such a direct final duplicating an event that
also has Indledende+Finale, so collapsing 'Direkte finale' into 'Final' (a
substring-match bug) destroys the only machine-readable para signal. These tests
pin the corrected mapping and the results-table keyword routing it depends on.
"""
import scrape_races


RESULTATER_PAGE = """
<div class="k-portlet__head">
  <h3 id="resultater" class="k-portlet__head-title">Resultater</h3>
</div>
<div class="k-portlet__body">
  <table class="table">
    <tr><td>41</td><td><a href="/loeb/?id=901">50 Fri - Damer</a></td><td>Direkte finale</td><td>10</td></tr>
    <tr><td>14</td><td><a href="/loeb/?id=902">100 Fri - Damer</a></td><td>Finale</td><td>8</td></tr>
    <tr><td>14</td><td><a href="/loeb/?id=903">100 Fri - Damer</a></td><td>Indledende</td><td>24</td></tr>
  </table>
</div>
"""


def _by_number(races):
    return {r["number"]: r for r in races}


def test_direkte_finale_preserved_as_timed_final():
    races = _by_number(scrape_races.scrape_race_list(RESULTATER_PAGE, meet_id=9775))
    # The direct final must NOT be collapsed into 'Final'.
    assert races[41]["type"] == "Timed final"


def test_plain_finale_and_indledende_unaffected():
    races = scrape_races.scrape_race_list(RESULTATER_PAGE, meet_id=9775)
    types = sorted(r["type"] for r in races)
    assert types == ["Final", "Heats", "Timed final"]


def test_results_keyword_timed_final_targets_finale_header():
    # A 'Direkte finale' box header contains 'finale', so the timed-final type
    # must search for the 'finale' keyword (not fall through to 'indledende').
    assert scrape_races._results_search_keyword("Timed final") == "finale"


def test_results_keyword_other_types_unchanged():
    assert scrape_races._results_search_keyword("Final") == "finale"
    assert scrape_races._results_search_keyword("Finale") == "finale"
    assert scrape_races._results_search_keyword("Swim-off") == "swim-off"
    assert scrape_races._results_search_keyword("Heats") == "indledende"
    assert scrape_races._results_search_keyword("Indledende") == "indledende"


# --- meet-level para classification --------------------------------------
# para = a 'Timed final' duplicating an event also run as Heats/Final in the
# same meet. The old race-number>=100 rule is wrong for 9775 (para below 100).

def _r(number, name, rtype):
    return {"number": number, "name": name, "type": rtype}


def test_para_is_timed_final_duplicating_a_prelim_final_event():
    races = [
        _r(43, "100 Fri - Damer", "Heats"),
        _r(43, "100 Fri - Damer", "Final"),
        _r(91, "100 Fri - Damer", "Timed final"),   # para: same event also has Heats/Final
    ]
    scrape_races._classify_races(races)
    klass = {(r["type"]): r["class"] for r in races}
    assert klass == {"Heats": "open", "Final": "open", "Timed final": "para"}


def test_distance_and_relay_timed_finals_stay_open():
    races = [
        _r(7, "800 Fri - Damer", "Timed final"),       # no Heats/Final twin -> able-bodied
        _r(20, "4 x 100 Fri - Herrer", "Timed final"),  # relay direct final -> able-bodied
    ]
    scrape_races._classify_races(races)
    assert all(r["class"] == "open" for r in races)


def test_para_low_number_below_100_is_still_caught():
    # 9775's regression: para event numbered 41 (< 100) must NOT be 'open'.
    races = [
        _r(8, "50 Fri - Damer", "Heats"),
        _r(8, "50 Fri - Damer", "Final"),
        _r(41, "50 Fri - Damer", "Timed final"),
    ]
    scrape_races._classify_races(races)
    para = [r for r in races if r["class"] == "para"]
    assert [r["number"] for r in para] == [41]
