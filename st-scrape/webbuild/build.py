"""Orchestrate the full JSON build and expose a CLI."""
import argparse
from pathlib import Path

from webbuild import queries
from webbuild.shape import write_json


def build_all(con, out: Path) -> list[Path]:
    out = Path(out)
    written = []

    def emit(rel, data):
        p = out / rel
        write_json(p, data)
        written.append(p)

    index = queries.build_index(con)
    emit("index.json", index)
    for cat in index["categories"]:
        code = cat["code"]
        meets = queries.build_meets(con, code)
        emit(f"{code}/meets.json", meets)
        for m in meets["meets"]:
            mid = m["meet_id"]
            emit(f"{code}/{mid}/meet.json", queries.build_meet(con, code, mid))
            races = queries.build_races(con, code, mid)
            emit(f"{code}/{mid}/races.json", races)
            for r in races["races"]:
                emit(f"{code}/{mid}/{r['race_key']}.json",
                     queries.build_race(con, code, mid, r["gender"],
                                        r["distance"], r["stroke"], r["course"]))
    return written


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build web JSON from the curated zone.")
    ap.add_argument("--out", required=True, type=Path, help="output directory")
    ap.add_argument("--s3", action="store_true",
                    help="(default) read the curated zone from S3 via analytics.loader")
    args = ap.parse_args(argv)
    from analytics.loader import connect
    con = connect()
    paths = build_all(con, args.out)
    print(f"wrote {len(paths)} files to {args.out}")


if __name__ == "__main__":
    main()
