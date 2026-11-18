"""CLI curate/class subcommands route to the right injected side effects."""
from ingestion import cli


class FakeOverrides:
    def __init__(self):
        self.calls = []

    def set_override(self, meet_id, race_id, klass, reason=""):
        self.calls.append((meet_id, race_id, klass, reason))


def test_curate_single_meet_invokes_curator():
    invoked = []
    cli.run(["curate", "8609"], registry=None, invoke=None,
            curate=lambda payload: invoked.append(payload) or {"launched": payload.get("meet_ids", [])},
            overrides=None)
    assert invoked == [{"meet_ids": ["8609"]}]


def test_curate_all_invokes_with_all_flag():
    invoked = []
    cli.run(["curate", "--all"], registry=None, invoke=None,
            curate=lambda payload: invoked.append(payload) or {"launched": payload.get("meet_ids", [])},
            overrides=None)
    assert invoked == [{"all": True}]


def test_class_set_writes_override():
    ov = FakeOverrides()
    cli.run(["class", "set", "8609", "213", "para", "--reason", "para-only"],
            registry=None, invoke=None, curate=None, overrides=ov)
    assert ov.calls == [("8609", 213, "para", "para-only")]


def test_curate_event_matches_the_s3_trigger_key():
    # The curate trigger Lambda only understands S3 ObjectCreated events on
    # raw/meet=<id>/results.jsonl; a bare {"meet_ids": ...} was a silent no-op.
    assert cli.curate_event(["8609", "12489"]) == {"Records": [
        {"s3": {"object": {"key": "raw/meet=8609/results.jsonl"}}},
        {"s3": {"object": {"key": "raw/meet=12489/results.jsonl"}}},
    ]}


def test_curate_reports_launched_meets(capsys):
    cli.run(["curate", "8609"], registry=None, invoke=None,
            curate=lambda payload: {"launched": ["8609"]}, overrides=None)
    assert "Curate launched: 8609" in capsys.readouterr().out


def test_curate_fails_loudly_when_meet_not_launched():
    import pytest
    with pytest.raises(SystemExit, match="8609"):
        cli.run(["curate", "8609"], registry=None, invoke=None,
                curate=lambda payload: {"launched": []}, overrides=None)


# --- curate --season/--course/--unscored: pick meets from the curated zone ---

def _curated_con():
    import duckdb
    from tests.analytics_fixtures import build_curated
    con = duckdb.connect()
    row = dict(rank=1, relay_count=1, distance=100, stroke="Fly", gender="M")
    build_curated(con, obt=[
        dict(row, result_id="a", meet_id="m1", season=2023, course="SCM", points=900),
        dict(row, result_id="b", meet_id="m2", season=2023, course="SCM", points=None),
        dict(row, result_id="c", meet_id="m3", season=2023, course="LCM", points=None),
        dict(row, result_id="d", meet_id="m4", season=2027, course="SCM", points=None),
    ])
    return con


def _curate(argv):
    invoked = []
    cli.run(["curate", *argv], registry=None, invoke=None,
            curate=lambda p: invoked.append(p) or {"launched": p.get("meet_ids", [])},
            overrides=None, connect=_curated_con)
    return invoked


def test_curate_season_and_course_selects_those_meets():
    assert _curate(["--season", "2023", "--course", "SCM"]) == [{"meet_ids": ["m1", "m2"]}]


def test_curate_unscored_selects_meets_without_points():
    assert _curate(["--unscored"]) == [{"meet_ids": ["m2", "m3", "m4"]}]
    assert _curate(["--unscored", "--season", "2023", "--course", "SCM"]) == [
        {"meet_ids": ["m2"]}]


def test_curate_filter_matching_nothing_launches_nothing(capsys):
    assert _curate(["--season", "1999"]) == []
    assert "No meets match" in capsys.readouterr().out


def test_curate_meet_id_and_filters_are_exclusive():
    import pytest
    with pytest.raises(SystemExit):
        _curate(["8609", "--season", "2023"])


# --- Lambda names come from CloudFormation when not exported ---

class FakeCfn:
    def describe_stack_resources(self, StackName):
        assert StackName == "SwimtrendsCuratedStack"
        return {"StackResources": [
            {"LogicalResourceId": "CurateTaskDef281B5269", "ResourceType": "AWS::ECS::TaskDefinition",
             "PhysicalResourceId": "td"},
            {"LogicalResourceId": "CurateTriggerE7F8C299", "ResourceType": "AWS::Lambda::Function",
             "PhysicalResourceId": "SwimtrendsCuratedStack-CurateTrigger-abc"},
        ]}


def test_stack_function_finds_lambda_by_logical_prefix():
    assert cli.stack_function(FakeCfn(), "SwimtrendsCuratedStack", "CurateTrigger") == \
        "SwimtrendsCuratedStack-CurateTrigger-abc"
