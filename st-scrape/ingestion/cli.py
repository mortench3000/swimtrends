"""swimtrends operational CLI.

  swimtrends register <meet_id> --categories DM-L,DMJ-L --end-date 2024-07-11
                                [--grace-hours N] [--deadline-hours N]
  swimtrends register <meet_id> --rescrape   # re-arm an existing meet
  swimtrends dispatch                      # normal due-check cycle
  swimtrends dispatch <meet_id> [--force]  # one meet now (force skips gates)
  swimtrends dispatch --all --force        # backfill every scheduled meet now

register talks to DynamoDB directly; dispatch invokes the dispatcher Lambda.
"""
import argparse
import json
import os
import sys


def build_parser():
    parser = argparse.ArgumentParser(prog="swimtrends",
                                     description="Swimtrends ingestion control.")
    sub = parser.add_subparsers(dest="command", required=True)

    reg = sub.add_parser("register", help="Add or update a meet in the registry.")
    reg.add_argument("meet_id")
    reg.add_argument("--categories",
                     help="Comma-separated, e.g. DM-L,DMJ-L (required unless --rescrape).")
    reg.add_argument("--end-date",
                     help="YYYY-MM-DD, the meet's last day (required unless --rescrape).")
    reg.add_argument("--grace-hours", type=int, default=None,
                     help="Hours after the meet's last day (23:59 local) before scraping. Default 6.")
    reg.add_argument("--deadline-hours", type=int, default=None,
                     help="Hours after which a meet is force-scraped even without confirmed results. Default 72.")
    reg.add_argument("--rescrape", action="store_true",
                     help="Re-arm an already-registered meet (status->scheduled, attempts=0, "
                          "error cleared). Does not need --categories/--end-date.")

    disp = sub.add_parser("dispatch", help="Invoke the dispatcher Lambda now.")
    disp.add_argument("meet_id", nargs="?", default=None)
    disp.add_argument("--all", action="store_true",
                      help="Target every scheduled meet (use with --force to backfill).")
    disp.add_argument("--force", action="store_true",
                      help="Bypass the grace/completeness gates.")

    cur = sub.add_parser("curate", help="Run the curated transform.")
    cur.add_argument("meet_id", nargs="?", default=None)
    cur.add_argument("--all", action="store_true",
                     help="Curate every meet (full rebuild).")

    cls = sub.add_parser("class", help="Manage authoritative class overrides.")
    cls_sub = cls.add_subparsers(dest="class_command", required=True)
    cls_set = cls_sub.add_parser("set", help="Set an override for one race.")
    cls_set.add_argument("meet_id")
    cls_set.add_argument("race_id", type=int)
    cls_set.add_argument("klass", choices=["open", "para"])
    cls_set.add_argument("--reason", default="")

    qry = sub.add_parser("query", help="Open a DuckDB analytics session over the curated zone.")
    qry.add_argument("--sql", default=None,
                     help="Run a single SQL statement and print the result, then exit.")

    return parser


def _default_query_connect():
    from analytics import loader
    return loader.connect()


def run(argv, *, registry, invoke, curate=None, overrides=None, connect=None):
    """Execute one CLI command. registry/invoke/curate/overrides injected."""
    args = build_parser().parse_args(argv)

    if args.command == "register":
        if args.rescrape:
            if registry.get(args.meet_id) is None:
                raise SystemExit(f"Cannot --rescrape meet {args.meet_id}: it is not registered.")
            registry.reset(args.meet_id)
            print(f"Re-armed meet {args.meet_id}: status=scheduled, attempts=0")
            return
        if not args.categories or not args.end_date:
            raise SystemExit("register requires --categories and --end-date "
                             "(omit them only with --rescrape).")
        if registry.get(args.meet_id) is not None:
            raise SystemExit(f"Meet {args.meet_id} is already registered; "
                             f"use --rescrape to re-arm it.")
        categories = [c.strip() for c in args.categories.split(",") if c.strip()]
        registry.put_meet(args.meet_id, categories, args.end_date,
                          grace_hours=args.grace_hours,
                          deadline_hours=args.deadline_hours)
        print(f"Registered meet {args.meet_id} ({', '.join(categories)}) "
              f"end_date={args.end_date} status=scheduled")
        return

    if args.command == "dispatch":
        if args.force and not args.meet_id and not args.all:
            raise SystemExit("Refusing to force-dispatch every scheduled meet without --all. "
                             "Use 'dispatch --all --force' to backfill, or pass a meet_id.")
        if args.all and not args.force:
            raise SystemExit("--all only applies with --force (e.g. 'dispatch --all --force'). "
                             "A plain due-check cycle is just 'dispatch'.")
        payload = {}
        if args.meet_id:
            payload["meet_ids"] = [args.meet_id]
        if args.force:
            payload["force"] = True
        result = invoke(payload)
        suffix = " (full due-check cycle)" if not payload else ""
        print(f"Dispatcher invoked with payload: {json.dumps(payload)}{suffix}")
        if result is not None:
            print(f"Dispatcher result: {result}")
        return

    if args.command == "curate":
        if args.all and args.meet_id:
            raise SystemExit("Pass a meet_id OR --all, not both.")
        if not args.all and not args.meet_id:
            raise SystemExit("curate needs a meet_id or --all.")
        payload = {"all": True} if args.all else {"meet_ids": [args.meet_id]}
        curate(payload)
        print(f"Curate invoked with payload: {json.dumps(payload)}")
        return

    if args.command == "class":
        if args.class_command == "set":
            overrides.set_override(args.meet_id, args.race_id, args.klass,
                                   reason=args.reason)
            print(f"Override set: meet {args.meet_id} race {args.race_id} "
                  f"-> {args.klass}")
        return

    if args.command == "query":
        con = (connect or _default_query_connect)()
        if args.sql:
            print(con.sql(args.sql))
            return 0
        import code
        banner = ("swimtrends analytics — DuckDB ready. "
                  "`con` is the connection; sql('SELECT …') prints a result.\n"
                  "Views: personal_best, event_leaderboard, swimmer_progression, "
                  "cross_era_best, club_leaderboard, age_group_ranking, pacing, "
                  "event_standard_by_season, final_cutline_by_season, …")
        code.interact(banner=banner, local={"con": con, "sql": lambda q: print(con.sql(q))})
        return 0


def main():
    argv = sys.argv[1:]

    # `query` is a local, read-only analytics session — it needs only AWS creds
    # for S3, not the ingestion/curate wiring or its env vars. Short-circuit
    # before touching REGISTRY_TABLE/DISPATCHER_FUNCTION so an analyst can run it.
    if build_parser().parse_args(argv).command == "query":
        run(argv, registry=None, invoke=None)
        return

    import boto3

    from ingestion.registry import MeetRegistry

    registry = MeetRegistry(os.environ["REGISTRY_TABLE"])
    lambda_client = boto3.client("lambda")
    function_name = os.environ["DISPATCHER_FUNCTION"]

    def invoke(payload):
        resp = lambda_client.invoke(
            FunctionName=function_name,
            InvocationType="RequestResponse",  # synchronous: report the result to the operator
            Payload=json.dumps(payload).encode("utf-8"),
        )
        body = resp["Payload"].read().decode("utf-8")
        return json.loads(body) if body else None

    from curate.overrides import ClassOverrides

    overrides = ClassOverrides(os.environ["OVERRIDES_TABLE"]) \
        if os.environ.get("OVERRIDES_TABLE") else None
    curator_fn = os.environ.get("CURATOR_FUNCTION")

    def curate(payload):
        if curator_fn is None:
            raise SystemExit("CURATOR_FUNCTION not set.")
        resp = lambda_client.invoke(
            FunctionName=curator_fn, InvocationType="Event",
            Payload=json.dumps(payload).encode("utf-8"))
        return resp["StatusCode"]

    run(argv, registry=registry, invoke=invoke,
        curate=curate, overrides=overrides)


if __name__ == "__main__":
    main()
