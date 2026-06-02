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
    return parser


def run(argv, *, registry, invoke):
    """Execute one CLI command. registry/invoke are injected for testing."""
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


def main():
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

    run(sys.argv[1:], registry=registry, invoke=invoke)


if __name__ == "__main__":
    main()
