"""Side-by-side model comparison for the meet evaluation. Hand-run only.

Runs the SAME agent configuration against the same digests with each candidate
model, applies the deterministic number check, and writes an HTML page plus a
stdout table of pass rate, tokens, cost and latency. A human reads the Danish
and picks the winner; the number check then stays in the pipeline forever.

Model ids and prices resolved 2026-07-27 from `aws bedrock list-foundation-models`
/ `list-inference-profiles` (region eu-west-1, account `swimtrends`) and the AWS
Price List API (the machine-readable backing data for the Bedrock pricing page:
Anthropic models are billed through the `AmazonBedrockFoundationModels`
marketplace offer, everything else through the `AmazonBedrock` offer;
eu-west-1 tables fetched from pricing.us-east-1.amazonaws.com/offers/v1.0/aws/...).
Two Claude tiers via their `eu.` cross-region inference profile (EU data
residency), one Nova and one Mistral as cheap controls, both confirmed present
directly in the eu-west-1 foundation-model list:

    eu.anthropic.claude-sonnet-5                 $2.20/MTok in, $11.00/MTok out
    eu.anthropic.claude-haiku-4-5-20251001-v1:0  $1.10/MTok in, $5.50/MTok out
    eu.amazon.nova-2-lite-v1:0                   $0.374/MTok in, $3.157/MTok out
    mistral.ministral-3-8b-instruct              $0.18/MTok in, $0.18/MTok out

Nova candidate swapped 2026-07-27 at the user's request: Nova Lite ->
Nova 2 Lite. `eu.amazon.nova-2-lite-v1:0` ("EU Amazon Nova 2 Lite") confirmed
present via `list-inference-profiles` for eu-west-1. Its `AmazonBedrock`
offer usagetypes are priced per 1K tokens, not per MTok — read directly from
the offer file:

    EU-Nova2.0Lite-input-tokens   $0.000374 / 1K tokens -> $0.374 / MTok
    EU-Nova2.0Lite-output-tokens  $0.003157 / 1K tokens -> $3.157 / MTok

(the plain `EU-` usagetypes, not `-flex` / `-priority` / `-batch` /
`-cross-region-global`, matching how the `eu.` regional profile is invoked
here and how the other three candidates were chosen).

Account-level model access (a candidate can still fail its first Converse call
with AccessDeniedException even though it is listed here) is NOT verified by
this comment block — that only happens when the harness is actually run.

Costs printed here are estimates from those figures; they are not billing data.
"""
import argparse
import html
import os
import sys
import time
from pathlib import Path

from analytics.loader import connect
from evaluation import agent as ag
from evaluation.check import check_numbers
from webbuild import digest as dg

# model_id -> (input $/MTok, output $/MTok), from the comment block above.
PRICES: dict[str, tuple[float, float]] = {
    "eu.anthropic.claude-sonnet-5": (2.20, 11.00),
    "eu.anthropic.claude-haiku-4-5-20251001-v1:0": (1.10, 5.50),
    "eu.amazon.nova-2-lite-v1:0": (0.374, 3.157),
    "mistral.ministral-3-8b-instruct": (0.18, 0.18),
}


def _cost(model_id, tokens_in, tokens_out):
    if model_id not in PRICES:
        return None
    pin, pout = PRICES[model_id]
    return (tokens_in * pin + tokens_out * pout) / 1_000_000


def _usage(result):
    """Token usage off a Strands AgentResult, defensively: the metrics shape
    varies by SDK version, so fall back to (0, 0, ok=False) rather than
    crashing a run. `ok` lets the caller tell "genuinely free" apart from
    "we don't actually know" — see run_one."""
    try:
        u = result.metrics.accumulated_usage
        return int(u.get("inputTokens", 0)), int(u.get("outputTokens", 0)), True
    except Exception:
        return 0, 0, False


def run_one(con, category, meet_id, model_id, guardrail_id, guardrail_version):
    """One (meet, model) cell of the comparison. Never raises: a bad meet id,
    a model without account access, a guardrail block, or an unreadable usage
    shape are all just a result with `error` set (or `usage_ok` False) rather
    than an exception — a single bad cell must not lose every other row
    already paid for in this run (digest-build and agent construction used to
    sit outside this try, which meant a typo'd meet id aborted the whole batch).

    A bogus or not-yet-curated meet id doesn't make dg.build raise — it
    degrades to an all-zero/None digest (webbuild.digest tolerates a missing
    meet by design, e.g. for an early-season meet with no prior history).
    Asking a model to write a coach report about a meet with zero scored
    swims wastes a call on nothing, so that's caught and skipped here too,
    before any agent is built — same guard as evaluation/__main__.py's run()."""
    from evaluation.cache import canonical_json
    t0 = time.monotonic()
    error, sections, offenders = None, [], set()
    tin, tout, usage_ok = 0, 0, False
    try:
        digest = dg.build(con, category, meet_id)
        if not digest["facts"]["entrants"]:
            error = f"empty digest: no scored swims for {category}/{meet_id}"
        else:
            agent = ag.build_agent(model_id=model_id, guardrail_id=guardrail_id,
                                   guardrail_version=guardrail_version)
            result = agent(f"<digest>{canonical_json(digest)}</digest>",
                           structured_output_model=ag.MeetEvaluation)
            sections = [{"heading": s.heading, "body": s.body}
                        for s in result.structured_output.sections]
            offenders = check_numbers("\n".join(s["body"] for s in sections), digest)
            tin, tout, usage_ok = _usage(result)
    except Exception as e:                      # a candidate that errors is a result
        error = f"{type(e).__name__}: {e}"
    return {
        "category": category, "meet_id": meet_id, "model_id": model_id,
        "seconds": round(time.monotonic() - t0, 1),
        "tokens_in": tin, "tokens_out": tout, "usage_ok": usage_ok,
        "cost": _cost(model_id, tin, tout) if usage_ok else None,
        "offenders": sorted(offenders), "sections": sections, "error": error,
    }


def _cells(r):
    """(tokens_in, tokens_out, cost) display strings for one row, shared by
    the HTML table and the stdout table so the two views can't drift apart.

    Two different kinds of "we don't have a number" here, rendered
    differently on purpose: an error (including the empty-digest skip above)
    never got a result back, so we KNOW nothing was spent — "-". A call that
    *succeeded* (sections + the number check both ran) but whose usage shape
    couldn't be parsed (see _usage) is genuinely unknown, likely non-zero —
    "?", never a silent 0 / $0.0000 that would look like a real, free call."""
    if r["error"]:
        return "-", "-", "-"
    if not r["usage_ok"]:
        return "?", "?", "?"
    cost = "-" if r["cost"] is None else f"{r['cost']:.4f}"
    return r["tokens_in"], r["tokens_out"], cost


def _html(rows) -> str:
    out = ["<meta charset='utf-8'><title>Model comparison</title>",
           "<style>body{font:15px/1.5 system-ui;max-width:1200px;margin:2rem auto}",
           "table{border-collapse:collapse;margin-bottom:2rem}",
           "td,th{border:1px solid #ccc;padding:4px 8px;text-align:left}",
           ".bad{color:#b00}.cols{display:flex;gap:1.5rem;align-items:flex-start}",
           ".col{flex:1;min-width:0}</style>",
           f"<p>prompt_version={html.escape(ag.PROMPT_VERSION)}</p>",
           "<table><tr><th>meet<th>model<th>numbers<th>in<th>out<th>$<th>s</tr>"]
    for r in rows:
        bad = "bad" if (r["offenders"] or r["error"] or not r["usage_ok"]) else ""
        verdict = r["error"] or (", ".join(r["offenders"]) if r["offenders"] else "ok")
        tin, tout, cost = _cells(r)
        out.append(
            f"<tr class='{bad}'><td>{html.escape(r['category'])}/{html.escape(r['meet_id'])}"
            f"<td>{html.escape(r['model_id'])}<td>{html.escape(verdict)}"
            f"<td>{tin}<td>{tout}<td>{cost}<td>{r['seconds']}</tr>")
    out.append("</table>")

    for meet in dict.fromkeys((r["category"], r["meet_id"]) for r in rows):
        out.append(f"<h2>{html.escape(meet[0])}/{html.escape(meet[1])}</h2><div class='cols'>")
        for r in [x for x in rows if (x["category"], x["meet_id"]) == meet]:
            out.append(f"<div class='col'><h3>{html.escape(r['model_id'])}</h3>")
            if r["error"]:
                out.append(f"<p class='bad'>{html.escape(r['error'])}</p>")
            for s in r["sections"]:
                out.append(f"<h4>{html.escape(s['heading'])}</h4>"
                           f"<p>{html.escape(s['body'])}</p>")
            out.append("</div>")
        out.append("</div>")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Compare models on meet evaluations.")
    ap.add_argument("--meets", required=True, help="comma-separated CATEGORY/MEET_ID")
    ap.add_argument("--models", required=True, help="comma-separated Bedrock model ids")
    ap.add_argument("--out", type=Path, default=Path("db/model-eval.html"))
    args = ap.parse_args(argv)

    guardrail_id = os.environ.get("EVAL_GUARDRAIL_ID")
    guardrail_version = os.environ.get("EVAL_GUARDRAIL_VERSION")
    if not (guardrail_id and guardrail_version):
        raise SystemExit("set EVAL_GUARDRAIL_ID and EVAL_GUARDRAIL_VERSION")

    con = connect()
    meets = [tuple(m.strip().split("/", 1)) for m in args.meets.split(",") if m.strip()]
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    args.out.parent.mkdir(parents=True, exist_ok=True)

    # This tool spends real money per row: write (overwrite) the HTML after
    # every meet's candidates finish, not just once at the end, so a run
    # interrupted partway (Ctrl-C, an error outside run_one) still leaves the
    # already-paid-for rows on disk instead of discarding them.
    print(f"{args.out} is updated after each meet — safe to open while this runs",
          flush=True)
    rows = []
    for category, meet_id in meets:
        for model_id in models:
            print(f"… {category}/{meet_id} on {model_id}", flush=True)
            rows.append(run_one(con, category, meet_id, model_id,
                                guardrail_id, guardrail_version))
        args.out.write_text(_html(rows), encoding="utf-8")

    print(f"\n{'model':40} {'numbers':10} {'in':>7} {'out':>7} {'$/meet':>9} {'s':>6}")
    for r in rows:
        verdict = "ERROR" if r["error"] else ("FAIL" if r["offenders"] else "ok")
        tin, tout, cost = _cells(r)
        print(f"{r['model_id'][:40]:40} {verdict:10} {tin!s:>7} "
              f"{tout!s:>7} {cost:>9} {r['seconds']:>6}")
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
