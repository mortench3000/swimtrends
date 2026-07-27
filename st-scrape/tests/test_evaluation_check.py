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
