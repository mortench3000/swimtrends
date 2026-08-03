from evaluation import check

DIGEST = {
    "meet": {"season": 2026, "name": "DM 2026", "date": "2026-04-10",
             "category": "DM-L", "course": "LCM"},
    "facts": {"entrants": 412, "events": 38, "clubs": 58, "juniors": 61,
              "median_points": 612, "elite_median_points": 701, "top_points": 812},
    "season_history": [
        {"season": 2026, "entrants": 412, "clubs": 58, "median_points": 612,
         "elite_median_points": 701},
        {"season": 2025, "entrants": 399, "clubs": 55, "median_points": 599,
         "elite_median_points": 688},
        {"season": 2024, "entrants": 391, "clubs": 54, "median_points": 585,
         "elite_median_points": 678},
        {"season": 2023, "entrants": 385, "clubs": 53, "median_points": 572,
         "elite_median_points": 665},
        {"season": 2022, "entrants": 378, "clubs": 51, "median_points": 558,
         "elite_median_points": 652},
        {"season": 2021, "entrants": 370, "clubs": 50, "median_points": 545,
         "elite_median_points": 640},
    ],
    "top_swims": [{"name": "Emma Sørensen", "club": "AGF", "event": "F 200m Fly (LCM)",
                   "time": "2:11.40", "points": 812, "rank": 1}],
    "by_stroke": [{"stroke": "Fly", "dist_group": "middel",
                   "median_points": 640, "prev5_median": 610}],
    "derived": {"median_points_vs_prev5_pct": 2},
}


def test_clean_report_passes():
    text = ("DM-L 2026 lå over niveauet: median 612 point mod 599 sidste sæson, "
            "og 412 deltagere fra 58 klubber. Emma Sørensens 2:11.40 (812 point) "
            "var stævnets bedste svømning.")
    assert check.check_numbers(text, DIGEST) == set()


def test_fabricated_number_is_caught():
    text = "Median-niveauet var 777 point."
    assert check.check_numbers(text, DIGEST) == {"777"}


def test_derived_percentage_from_the_digest_is_allowed():
    assert check.check_numbers("Niveauet lå 2% over 5-sæsons-snittet.", DIGEST) == set()


def test_a_negative_delta_is_licensed_signed_and_unsigned():
    """Real deltas are negative -- DM-L's production digest carried -36, -29,
    -21 -- and Danish prose writes them unsigned ("faldt 36 point"), because
    the direction is in the verb. So the digest's -36 has to license both "36"
    and "-36". No fixture here contained a single negative number, which left
    the sign-stripping add in _walk (and the same property for a negative
    derived percentage) entirely untested."""
    d = {**DIGEST,
         "by_stroke": [{"stroke": "Bryst", "dist_group": "sprint",
                        "median_points": 574, "prev5_median": 610, "delta": -36}],
         "derived": {"median_points_vs_prev5_pct": -7}}
    assert check.check_numbers("Brystsvømning faldt 36 point.", d) == set()
    assert check.check_numbers("Brystsvømning: delta -36 point.", d) == set()
    assert check.check_numbers("Niveauet lå 7% under snittet.", d) == set()
    assert check.check_numbers("Niveauet lå -7% fra snittet.", d) == set()
    # still a real check: a delta the digest does not contain is caught
    assert check.check_numbers("Brystsvømning faldt 44 point.", d) == {"44"}


def test_undeclared_percentage_is_caught():
    assert check.check_numbers("Niveauet lå 9% over snittet.", DIGEST) == {"9"}


def test_time_is_matched_with_and_without_the_leading_minute():
    assert check.check_numbers("Hun svømmede 2:11.40.", DIGEST) == set()
    assert check.check_numbers("Hun svømmede 2:11,40.", DIGEST) == set()   # Danish comma
    assert check.check_numbers("Hun svømmede 2:12.40.", DIGEST) == {"2:12.40"}


def test_window_length_and_seasons_are_allowed():
    # "5-sæsons" and a season reference must not trip the check
    assert check.check_numbers("over de sidste 5 sæsoner siden 2025", DIGEST) == set()


def test_ordinal_ranks_from_top_swims_are_allowed():
    assert check.check_numbers("Hun blev nummer 1.", DIGEST) == set()


def test_a_bare_five_is_not_licensed_by_a_short_history():
    """The window length is licensed from len(season_history), never as a
    hardcoded literal — otherwise any fabricated '5' publishes silently."""
    short = {**DIGEST, "season_history": DIGEST["season_history"][:2]}
    assert check.check_numbers("Der blev sat 5 danske rekorder.", short) == {"5"}


def test_date_digits_are_not_licensed():
    """meet.date must not license bare numbers: '2026-04-10' licensing '10'
    made a fabricated '10 sølvmedaljer' publishable."""
    assert check.check_numbers("Der var 10 sølvmedaljer.", DIGEST) == {"10"}
    assert check.check_numbers("Hun svømmede 200 Fly.", DIGEST) == set()   # distance still allowed


def test_danish_thousands_separator_matches_a_four_digit_digest_value():
    d = {**DIGEST, "facts": {**DIGEST["facts"], "top_points": 1234}}
    assert check.check_numbers("Topsvømmeren fik 1.234 point.", d) == set()
    # Decimals absent from digest should still be caught
    assert check.check_numbers("Hun svømmede 2,50 sekunder hurtigere.", DIGEST) == {"2.50"}


def test_bare_sprint_time_from_top_swims_is_licensed():
    """Sub-minute races (50m/100m) have no minute component in curated data
    (e.g. "24.66", not "0:24.66") — the time check must still license them."""
    d = {**DIGEST, "top_swims": [{"name": "Ida Møller", "club": "AGF",
                                   "event": "F 50m Fri (LCM)", "time": "24.66",
                                   "points": 700, "rank": 1}]}
    assert check.check_numbers("Han svømmede 24.66.", d) == set()
    assert check.check_numbers("Han svømmede 24,66.", d) == set()   # Danish comma


def test_near_miss_sprint_time_is_still_caught():
    """Licensing must key on the digest's actual value, not merely the
    bare-time shape — a wrong time is still fabricated."""
    d = {**DIGEST, "top_swims": [{"name": "Ida Møller", "club": "AGF",
                                   "event": "F 50m Fri (LCM)", "time": "24.66",
                                   "points": 700, "rank": 1}]}
    assert check.check_numbers("Han svømmede 24.67.", d) == {"24.67"}


def test_club_name_digits_are_licensed():
    """Danish club names carry digits ("MK31", "A6 JGI-Swim"). The model names
    the swimmer's club because the prompt licenses it, so those digits are not
    fabrications — and flagging them burns the one rewrite the meet gets, which
    is what left DM-K/7088 unpublished."""
    d = {**DIGEST, "top_swims": [{"name": "Ida Møller", "club": "Svømmeklubben MK31",
                                  "event": "F 50m Fri (LCM)", "time": "24.66",
                                  "points": 700, "rank": 1}]}
    assert check.check_numbers("Ida Møller fra Svømmeklubben MK31 vandt.", d) == set()
    # A club's digits license only themselves — not arithmetic built from them.
    assert check.check_numbers("Klubben vandt 311 gange.", d) == {"311"}


def test_meet_name_year_is_licensed():
    """meet.name is the meet's own displayed title (e.g. "DM Kortbane 2016")
    — a model naturally quotes it, so its digits must be licensed."""
    d = {**DIGEST, "meet": {**DIGEST["meet"], "name": "DM Kortbane 2016"}}
    assert check.check_numbers("Rekorden faldt ved DM Kortbane 2016.", d) == set()


# --- check_genders -----------------------------------------------------------
# A gendered event claim is a factual statement about a named athlete that no
# other gate can see: check_numbers inspects numeric tokens only, and the
# guardrail scores a whole section, where one wrong word costs almost nothing.
# Measured on the real DM-L/9775 report: "herrernes 50m Ryg" for an F event
# scored 0.88 grounding, against 0.92 for the same text with the gender fixed.

def _swim(event):
    return {"name": "X", "club": "AGF", "event": event, "time": "28.50",
            "points": 848, "rank": 1}


def test_gendered_claim_contradicting_the_digest_is_caught():
    """The published DM-L/9775 sentence, verbatim in shape: the digest offers
    only F 50m Ryg and the report called it a men's race."""
    d = {**DIGEST, "top_swims": [_swim("F 50m Ryg (LCM)")]}
    assert check.check_genders(
        "Pauline Mahieu vandt herrernes 50m Ryg med 848 point.", d) == {
            "herrernes 50m Ryg"}


def test_gendered_claim_matching_the_digest_passes():
    d = {**DIGEST, "top_swims": [_swim("F 50m Ryg (LCM)")]}
    assert check.check_genders("Hun vandt damernes 50m Ryg.", d) == set()


def test_the_raw_marker_form_is_checked_too():
    """Rule 9 lets the model write the digest's own "M 50m Ryg" instead of
    "herrernes", so a gate that only reads the Danish words is half a gate."""
    d = {**DIGEST, "top_swims": [_swim("F 50m Ryg (LCM)")]}
    assert check.check_genders("Vinderen tog M 50m Ryg.", d) == {"M 50m Ryg"}
    assert check.check_genders("Vinderen tog F 50m Ryg.", d) == set()


def test_an_event_held_for_both_genders_licenses_either():
    d = {**DIGEST, "top_swims": [_swim("F 50m Ryg (LCM)"), _swim("M 50m Ryg (LCM)")]}
    assert check.check_genders("herrernes 50m Ryg og damernes 50m Ryg", d) == set()


def test_an_event_absent_from_the_digest_is_not_this_check_s_business():
    """top_swims is a top-N list, so most of a meet's events are missing from
    it. Flagging those would reject correct prose about a race the digest
    simply doesn't carry — a different problem than a contradicted marker."""
    d = {**DIGEST, "top_swims": [_swim("F 50m Ryg (LCM)")]}
    assert check.check_genders("herrernes 1500m Fri var tæt.", d) == set()


def test_prose_without_a_gendered_event_claim_is_clean():
    d = {**DIGEST, "top_swims": [_swim("F 50m Ryg (LCM)")]}
    assert check.check_genders("Blandt herrerne var niveauet højt.", d) == set()
    assert check.check_genders("Medianen faldt 12 point.", d) == set()


# --- check_attribution -------------------------------------------------------
# The model attaches a real figure to the wrong athlete. Observed on a
# regenerated DMJ-L/11712: "Lucas Linderoth ... M 1500m Fri (772 point)", where
# 772 is Mathias Hald's result, plus "fire sejre" for a swimmer with three.
# Every number was real, so check_numbers passed; the guardrail passed too. Only
# the binding between name and figure was wrong.

ATTRIB = {**DIGEST, "top_swims": [
    {"name": "Mathias Hald", "club": "Lyngby", "event": "M 1500m Fri (LCM)",
     "time": "15:48.80", "points": 772, "rank": 1},
    {"name": "Mathias Hald", "club": "Lyngby", "event": "M 400m Fri (LCM)",
     "time": "4:00.79", "points": 763, "rank": 1},
    {"name": "Lucas Linderoth", "club": "Sigma", "event": "M 200m IM (LCM)",
     "time": "2:04.74", "points": 763, "rank": 1},
    {"name": "Lucas Linderoth", "club": "Sigma", "event": "M 100m Fri (LCM)",
     "time": "50.67", "points": 767, "rank": 1},
]}


def test_a_figure_credited_to_the_wrong_swimmer_is_caught():
    text = ("Lucas Linderoth fra Sigma satte resultat i fire discipliner: "
            "M 100m Fri med 767 point og M 1500m Fri med 772 point.")
    assert check.check_attribution(text, ATTRIB) == {"Lucas Linderoth: 772"}


def test_correct_attribution_passes():
    text = ("Mathias Hald vandt M 1500m Fri med 772 point og M 400m Fri med "
            "763 point. Lucas Linderoth vandt M 100m Fri med 767 point.")
    assert check.check_attribution(text, ATTRIB) == set()


def test_a_figure_two_swimmers_share_licenses_either():
    """763 is both Mathias Hald's 400m Fri and Lucas Linderoth's 200m IM."""
    assert check.check_attribution("Mathias Hald tog 763 point.", ATTRIB) == set()
    assert check.check_attribution("Lucas Linderoth tog 763 point.", ATTRIB) == set()


def test_a_figure_with_no_named_swimmer_before_it_is_not_judged():
    assert check.check_attribution("Topresultatet blev 772 point.", ATTRIB) == set()


def test_an_aggregate_figure_is_never_judged_as_an_attribution():
    """A median that happens to equal a swim's points has ambiguous provenance,
    and rejecting correct prose is worse than missing one misattribution."""
    d = {**ATTRIB, "facts": {**ATTRIB["facts"], "median_points": 772}}
    assert check.check_attribution("Lucas Linderoth ... medianen på 772 point.",
                                   d) == set()


def test_a_name_far_upstream_does_not_bind_a_later_figure():
    text = "Lucas Linderoth vandt. " + "Feltet var jævnt. " * 20 + "772 point."
    assert check.check_attribution(text, ATTRIB) == set()


def test_a_club_between_the_name_and_the_figure_does_not_break_the_binding():
    """Reports say "X fra <Club> vandt ... N point", so the club sits between
    the swimmer and the figure. It must be stepped over, not treated as the
    claimed owner."""
    d = {**ATTRIB, "top_swims": [{**ATTRIB["top_swims"][0], "club": "Lyngby Svømmeklub"},
                                 *ATTRIB["top_swims"][1:]]}
    assert check.check_attribution(
        "Mathias Hald fra Lyngby Svømmeklub vandt med 772 point.", d) == set()
    assert check.check_attribution(
        "Lucas Linderoth fra Lyngby Svømmeklub vandt med 772 point.", d) == {
            "Lucas Linderoth: 772"}


def test_an_unknown_name_between_them_makes_the_binding_unjudgeable():
    """If the report names somebody the digest does not carry, the figure
    belongs to that unknown name, not to the last digest swimmer upstream.
    Judging it would blame the wrong person — as it did on DM-K/10340, where
    the check reported "Karoline Barrett: 845" for a sentence crediting
    Frederik Lindholm. Naming a non-digest swimmer is its own violation; this
    check stays silent rather than mislabel it."""
    # Discriminating on purpose: the last *digest* name upstream (Lucas) does
    # not own 772, so a naive nearest-name binding flags him — for a figure the
    # sentence credits to someone else entirely.
    text = "Lucas Linderoth vandt 767 point. Ukendt Svømmer scorede 772 point."
    assert check.check_attribution(text, ATTRIB) == set()


def test_a_threshold_figure_is_not_an_attribution():
    """"over 850 point" is a comparison, not a claim that the last-named
    swimmer scored 850. Caught on DM-L/6516, where the sentence "Blandt de tre
    øvrige pointgennemsnit på over 850 point" bound 850 to Pernille Blume."""
    text = ("Mathias Hald svømmede stærkt. Blandt resultaterne på over 772 "
            "point var feltet tæt.")
    assert check.check_attribution(text, ATTRIB) == set()


def test_a_range_endpoint_is_not_an_attribution():
    """"720-750 point" describes a band. Caught on DMJ-L/8609, where it bound
    750 to Clara Rybak-Andersen."""
    text = "Lucas Linderoth vandt. Flere svømmere præsterede på 763-772 point."
    assert check.check_attribution(text, ATTRIB) == set()
    assert check.check_attribution(
        "Lucas Linderoth præsterede på 763–772 point.", ATTRIB) == set()


_ENTITY_DIGEST = {
    "meet": {"name": "DM Langbane 2023", "date": "2023-04-10"},
    "facts": {"entrants": 412, "median_points": 612, "top_points": 764},
    "season_history": [],
    "top_swims": [
        {"name": "Emilie Beckmann", "club": "Swim Team Odense",
         "event": "F 50m Fly (LCM)", "time": "26.10", "points": 822, "rank": 1},
    ],
    "clubs": [
        {"club": "Svømmeklubben MK31", "swimmers": 14, "titles": 5,
         "podiums": 11, "rank": 1},
        {"club": "A6 JGI-Swim", "swimmers": 9, "titles": 2, "podiums": 6,
         "rank": 2},
    ],
    "multi_title_swimmers": [
        {"name": "Mathias Christensen", "club": "Sigma Swim Allerød",
         "titles": 4, "strokes": ["Bryst", "Fly", "IM"],
         "wins": [{"event": "M 200m IM (LCM)", "points": 764},
                  {"event": "M 100m Fly (LCM)", "points": 729}]},
    ],
    "by_stroke": [],
    "derived": {},
}


def test_club_table_names_license_their_own_digits():
    """Club names carry digits ("MK31", "A6"). The prompt licenses naming a
    club, so those digits arrive by design -- flagging them as fabricated
    spends the meet's single rewrite on a false positive, which is what left
    DM-K/7088 unpublished."""
    text = ("Svømmeklubben MK31 vandt 5 titler og 11 podieplaceringer. "
            "A6 JGI-Swim fulgte med 2 titler.")
    assert check.check_numbers(text, _ENTITY_DIGEST) == set()


def test_a_multi_title_swimmers_club_also_licenses_its_digits():
    assert "31" in check.allowed_numbers(_ENTITY_DIGEST)
    d = {**_ENTITY_DIGEST, "clubs": [],
         "multi_title_swimmers": [{"name": "X Y", "club": "MK31", "titles": 3,
                                   "strokes": ["Fri"], "wins": []}]}
    assert "31" in check.allowed_numbers(d)


def test_a_win_is_bound_to_the_swimmer_who_won_it():
    """The block's points are the only figures in the report that nothing else
    protects: they are absent from top_swims by construction."""
    assert check.points_owners(_ENTITY_DIGEST)["764"] == {"mathias christensen"}
    good = "Mathias Christensen vandt 200m IM med 764 point."
    assert check.check_attribution(good, _ENTITY_DIGEST) == set()
    bad = "Emilie Beckmann vandt fire titler med 764 point."
    assert check.check_attribution(bad, _ENTITY_DIGEST) == {"Emilie Beckmann: 764"}


def test_a_gender_flip_on_a_win_is_caught():
    """Same defect class as DM-L/9775's "vandt herrernes 50m Ryg" against an F
    digest row -- every number right, the claim false."""
    assert check.check_genders("Han vandt herrernes 200m IM.", _ENTITY_DIGEST) == set()
    assert check.check_genders("Hun vandt damernes 200m IM.",
                               _ENTITY_DIGEST) == {"damernes 200m IM"}


def test_club_aggregates_are_not_treated_as_a_swimmers_result():
    """A club's title count is nobody's points. If it collides with a real
    points value the provenance is ambiguous, so the attribution check must
    stay quiet rather than credit it to the nearest name."""
    d = {**_ENTITY_DIGEST,
         "clubs": [{"club": "AGF", "swimmers": 3, "titles": 764, "podiums": 1,
                    "rank": 1}]}
    assert "764" not in check.points_owners(d)
