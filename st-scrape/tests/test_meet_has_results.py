"""meet_has_results() returns True only when the meet page lists races."""
import scrape_races


def test_returns_true_when_races_present(monkeypatch):
    monkeypatch.setattr(scrape_races, "scrape_race_list", lambda html, mid: [{"race_id": 1}])

    class FakeResp:
        text = "<html>has races</html>"

    monkeypatch.setattr(scrape_races, "fetch", lambda url, timeout=30: FakeResp())
    assert scrape_races.meet_has_results("10970") is True


def test_returns_false_when_no_races(monkeypatch):
    monkeypatch.setattr(scrape_races, "scrape_race_list", lambda html, mid: [])

    class FakeResp:
        text = "<html>nothing yet</html>"

    monkeypatch.setattr(scrape_races, "fetch", lambda url, timeout=30: FakeResp())
    assert scrape_races.meet_has_results("10970") is False


def test_returns_false_on_fetch_error(monkeypatch):
    def boom(url, timeout=30):
        raise RuntimeError("network down")

    monkeypatch.setattr(scrape_races, "fetch", boom)
    assert scrape_races.meet_has_results("10970") is False
