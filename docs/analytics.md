# Analytics (Spec 3): local DuckDB over the curated zone

Read-only ad-hoc analysis of the curated Parquet, straight from S3. For the
operational side — registering meets, triggering scrapes/curation, class
overrides, `pending` — see [ingestion.md](ingestion.md).

## Prerequisites
- `pip install -r st-scrape/requirements.txt` (provides `duckdb`).
- AWS credentials for the `swimtrends` profile (eu-west-1). `loader.connect()`
  defaults `AWS_PROFILE` to `swimtrends`, so the credential-chain secret resolves
  your `~/.aws/credentials` automatically (override by exporting `AWS_PROFILE`).
  First run downloads the `httpfs`/`aws` extensions.

## Interactive REPL
```bash
cd st-scrape
.venv/bin/python -m ingestion.cli query
```
`con` is the DuckDB connection; `sql("…")` prints a result. All views are loaded.

There is no `swimtrends` console script in this repo, so **`swimtrends` below is
shorthand for `.venv/bin/python -m ingestion.cli`**, run from `st-scrape/`. Alias
it if you want the short form to work verbatim:
```bash
alias swimtrends='.venv/bin/python -m ingestion.cli'
```

One-shot (how fast you had to swim to make the 200 breaststroke final at DM-L,
per season):
```bash
swimtrends query --sql "SELECT season, gender, cutline_time FROM final_cutline_by_season \
  WHERE category='DM-L' AND distance=200 AND stroke='Bryst' ORDER BY season, gender"
```

### More example queries
```bash
# Junior championship top 5 — 100m Fly women, 2026 (ranked on the qualifying swim)
swimtrends query --sql "SELECT junior_rank, name, completed_time FROM junior_championship \
  WHERE season=2026 AND distance=100 AND stroke='Fly' AND gender='F' ORDER BY junior_rank LIMIT 5"

# One swimmer's medals across every championship
swimtrends query --sql "SELECT category, gold, silver, bronze FROM medal_count \
  WHERE swimmer_id='26884' ORDER BY gold DESC"

# Which DM-L meets a swimmer has competed in
swimtrends query --sql "SELECT season, meet_name, swims FROM swimmer_meets \
  WHERE swimmer_id='26884' AND category='DM-L' ORDER BY season"

# All-time 100m Freestyle (SCM) top 10 by best time, with WA points
swimtrends query --sql "SELECT name, best_time, points FROM personal_best \
  WHERE stroke='Fri' AND distance=100 AND course='SCM' ORDER BY best_centiseconds LIMIT 10"

# How an event standard moved across seasons (best + top-3-avg + top-8-avg, centiseconds)
swimtrends query --sql "SELECT season, gender, best_cs, top3_avg_cs, top8_avg_cs \
  FROM event_standard_by_season WHERE category='DM-L' AND distance=100 AND stroke='Fly' ORDER BY season, gender"
```
Column values are Danish: stroke `Fri`/`Ryg`/`Bryst`/`Fly`/`IM`, course `LCM`/`SCM`,
gender `M`/`F` (see Vocabulary below). SCM seasons are the *next* year — a
December 2025 meet is season 2026.

## Data overview (what's in the zone)
Top-level, read-only catalog queries — no SQL needed:
```bash
swimtrends summary                       # totals: meets, results, swimmers, seasons, categories
swimtrends categories                    # per-category coverage: meets, season span, results
swimtrends meets                         # every meet, sorted by season, with race/result/DSQ counts
swimtrends meets --category DM-K         # filter by category
swimtrends meets --season 2026           # filter by season (filters compose)
```
`races` = distinct races, `results` = result rows, `dsq` = disqualifications
(rank -1). Like `query`, these need only AWS credentials for S3.

## From a notebook / Python
```python
from analytics import loader
con = loader.connect()
con.sql("SELECT * FROM event_standard_by_season WHERE category='DM-L'")
```

### Jupyter in VS Code
A ready-to-run starter notebook lives at `st-scrape/notebooks/explore.ipynb`
(coverage overview, best times, the final cut-line trend, and event-standard
plots — all using the real view columns).

One-time setup:
1. Install the analyst tooling into the venv:
   `cd st-scrape && .venv/bin/pip install -r requirements-notebook.txt`
   (adds `ipykernel`, `pandas`, `matplotlib`).
2. Register the venv as a Jupyter kernel (so VS Code lists it by name):
   `.venv/bin/python -m ipykernel install --user --name swimtrends --display-name "Swimtrends (st-scrape)"`
3. Install the VS Code **Python** + **Jupyter** extensions if you haven't.

Then open `explore.ipynb` and pick the **Swimtrends (st-scrape)** kernel
(top-right). The workspace `.vscode/settings.json` points the default
interpreter at `st-scrape/.venv` and sets the notebook working dir to
`st-scrape/`. The notebook's first cell also self-locates the `analytics`
package, so it runs even if launched from elsewhere. `con.sql(...)` returns a
DuckDB result; the `q(...)` helper returns a pandas DataFrame for tables/plots.

## Web JSON build
Generate the static JSON the web app serves (reads the curated zone from S3):

    cd st-scrape && AWS_PROFILE=swimtrends .venv/bin/python -m webbuild --out ../web/public/data

Output mirrors the app's URL layout (index.json, <category>/meets.json,
<category>/<meet_id>/{meet,races}.json, <category>/<meet_id>/<race_key>.json).

## View catalog
- **Best times / ranking:** `personal_best`, `season_best`, `event_leaderboard`
- **Progression:** `swimmer_progression`, `biggest_improvers`, `cross_era_best`,
  `swimmer_meets` (which meets a `swimmer_id` competed in, per category),
  `medal_count` (gold/silver/bronze finals finishes per swimmer, per category)
- **Aggregates:** `club_leaderboard`, `age_group_ranking`, `meet_summary`
- **Pacing:** `pacing`
- **Juniors:** `junior_championship` (junior title standings per DMJ-L event).
  A swim is junior when competition-season age is 16-18 (`is_junior` on
  `results`, a floor *and* a ceiling — sub-16 qualifiers at a senior meet are
  too young for the title; the band slides by season, e.g. 2026 → born
  2008-2010). The title is decided from the **qualifying** swim, so
  `junior_championship` ranks juniors by their heats (or timed-final, for
  800/1500) time — never the senior final, which most juniors never reach.
  `junior_rank` 1/2/3 = gold/silver/bronze. e.g. `SELECT * FROM
  junior_championship WHERE season=2026 AND distance=100 AND stroke='Fly'
  AND gender='M' ORDER BY junior_rank`.
- **Field evolution:** `event_standard_by_season`, `final_cutline_by_season`,
  `cutline_at(n)` (cut-line for an arbitrary final size), `results_by_category`,
  `prelim_ranked`. `final_cutline_by_season` / `cutline_at(n)` expose an
  `entrants` column (the prelim field size) so you can tell a well-defined
  cut-line (`entrants >= n`) from a thin field. An event swum as a *timed final*
  (no heats — common for small fields) has no prelim, so it is **absent** from
  these views entirely; use `event_standard_by_season` for an unbroken trend.
- **Relays:** `relay_results` (relay swims only, DQs excluded),
  `relay_results_by_category`, `relay_event_standard_by_season`. Relays are swum
  as timed finals, so there is no relay cut-line view. `relay_count` is part of
  the event key so different relay sizes stay distinct (every curated relay is
  currently a 4x). `gender` is `M`/`F` in the data so far, though `X` (mixed) is
  a legal value. Columns mirror `event_standard_by_season` minus the cut-line
  ones: `swims`, `best_cs`, `median_cs`, `top8_avg_cs` — note `median_cs`, not
  the individual view's `top3_avg_cs`.

Base views: `results` (1 row per result, with
`age`/`is_junior`/`phase`/`is_relay`/`is_dq`) and `individual_results` (real
individual swims only).

## Vocabulary (curated column values)
- **stroke** is Danish: `Fri` (free), `Ryg` (back), `Bryst` (breast), `Fly`,
  `IM` / `HM` (individual/team medley).
- **course**: `LCM` (50 m) / `SCM` (25 m). **gender**: `M` / `F`.
- **phase** (derived from race `type`): `heats`, `final`, `timed_final`.
- **category**: meet qualifier — `DM-L`, `DMJ-L`, `DO`, … (the championship key).

## Notes
- New meets are queryable the moment they are curated — no refresh step.
- `category` (DM-L, DMJ-L, …) is meet-level; a meet in two categories pools into
  both in the field-evolution views.

## AI meet evaluations

Each meet page can carry a short Danish coach-style evaluation, generated
offline and cached. `make web-eval` fills the cache and writes
`web/public/data/<cat>/<meet>/evaluation.json`; `make web-refresh` runs it
between `webbuild` and the S3 sync.

**To publish reports and nothing else, use `make web-eval-deploy`** — it runs
`web-eval`, syncs only `*/evaluation.json`, and invalidates `/data/*`. That is
the target for a prompt edit, a new check, or a re-roll of a refused meet.
`web-refresh` would also publish them, but it rebuilds the whole data zone
first (~50 minutes) to regenerate files that are already correct. Confirm with
`make web-eval-verify`, which compares each local file's md5 against the served
object's ETag: the sync's upload list is *not* a record of what changed,
because `web-eval` rewrites all 41 files every run and sync compares mtimes.

This step needs `strands-agents` and `pydantic`, which live in
`st-scrape/requirements-eval.txt` rather than `requirements.txt` — the Fargate
images install the latter and import neither. `requirements-dev.txt` pulls the
eval file in, so the local venv and CI already have them.

### Model choice

Four candidates were compared with `evaluation/compare.py` on three meets —
a large senior LCM championship, the same meet junior-scoped, and the
earliest meet on record (no prior season history):

| model | numbers | $/meet | note |
|---|---|---|---|
| Claude Haiku 4.5 (`eu.anthropic.claude-haiku-4-5-20251001-v1:0`) | ok ×3 | ~$0.0069 | **chosen** — the only candidate with a genuine coach voice |
| Nova 2 Lite (`eu.amazon.nova-2-lite-v1:0`) | ok ×3 | ~$0.0021 | accurate but reads like a narrated table |
| Ministral 3 8B (`mistral.ministral-3-8b-instruct`) | 1 of 3 | ~$0.0010 | fabricated figures; broken Danish |
| Claude Sonnet 5 (`eu.anthropic.claude-sonnet-5`) | — | — | not available for this account |

The `$/meet` figures are **model tokens only** — Bedrock Guardrails are billed
separately per text unit, and the guardrail is now applied to the output as well
as the input, so the real cost per generated meet is a little higher than the
table says.

#### Haiku 4.5 was replaced by Sonnet 4.6 (2026-08-03)

That comparison scored *facts*, not language, and Haiku's Danish did not hold up
across a full batch. Counting every word appearing ≤3× across the 40 published
reports found ~60 non-words in three classes:

* **Bokmål drift** — `hadde`, `blant`, `antall`, `deltakere`, `etterfulgt`,
  `gjennomsnitt`, `høyeste`, `plasseringer`, `poengsum`, `oppnådde`, `vant`,
  `økning`, `historikk`, `medaljespeilet`
* **English intrusion** — `stroketyper`, `mediumdistance`, `longbanenivået`,
  `podiums`, `performance`
* **Invented words** — `førtede` (for `førte`), `guldmedajer`,
  `topsværgmelser`, `sprintintersvig`, `velrepsentierede`, `conquisterede`

Nothing in the pipeline can catch this: `check_numbers` reads digits,
`check_genders`/`check_attribution` read specific bindings, and the guardrail
scores *grounding* — a malformed verb in a factually correct sentence still
scores as supported. All four retry branches cite numbers, gender, attribution
or a blocked section, so a language error survives every attempt by
construction. Fluency is the model's job, not a checker's: a gate can reject,
it cannot write better Danish. A dictionary gate was considered and rejected —
Danish compounding is productive, so `femårsgennemsnittet` and
`medaljeplacerede` are correct and in no word list.

`EVAL_MODEL_ID` is therefore `eu.anthropic.claude-sonnet-4-6` (the Makefile
default). Regenerating all 41 meets on it cost **$2.63** (268k in / 106k out,
~$0.075/meet, ~11× Haiku) and cut the residue to ~16 sentences in 35 reports —
mostly transposition typos (`podieplacerigner`), a few Scandinavian forms
(`deltakertal`, `grenar`, `langtbane`) and digest jargon leaking through rule 8
(`digest.derived angiver …`, `negative deltas`, `over 46 events`).

One trap when changing the model: `MAX_TOKENS` is sized for the chosen model.
Sonnet spends ~2000 output tokens on the same 300-word brief where Haiku spent
under 1200, and strands raises `MaxTokensReachedException` rather than returning
the partial report — so an undersized ceiling skips *every* meet and
`_drop_stale` then removes its published page. It is also in the cache key.

### Guardrail

`SwimtrendsEvaluationStack` defines one guardrail: four denied topics
(`TalentProjection`, `PhysiqueAndHealth`, `PersonalCriticism`,
`PersonalDetails`), content filters (HATE / INSULTS / SEXUAL at MEDIUM input and
HIGH output, VIOLENCE / MISCONDUCT at MEDIUM both ways, PROMPT_ATTACK MEDIUM on
input only), and a contextual grounding check at 0.5 — `GROUNDING` only, no
`RELEVANCE` filter.

The grounding check needs the digest tagged `grounding_source` and the question
tagged `query`, and Strands sends neither through a plain-string prompt — so
until the report started going through an explicit `ApplyGuardrail` call
(`evaluation/agent.py`, `OutputGuard`), **contextual grounding never ran at any
threshold**, and the denied topics only ever assessed the input. What it catches
is something like a model inferring geographic spread from a bare club count — a
claim the deterministic number check cannot see either, since it isn't a number.

The threshold and the shape of the check are measured, not guessed, and the two
are inseparable — **the report is checked one section at a time**, five
`ApplyGuardrail` calls per generated meet:

| what was scored | grounding score |
| --- | --- |
| six real reports, whole report as one block | 0.40 – 0.81 |
| those same reports, section by section | 0.63 – 0.95 |
| deliberately ungrounded sections (invented number, causal claim, inferred geography, talent projection) | 0.00 – 0.34 |
| a plain recitation of digest facts | 0.97 |

Concatenating four sections depresses the score below anything a truthful report
reaches, so the original whole-report check at 0.85 blocked 100% of real reports;
per section, 0.5 sits in the middle of a wide gap. A block names the offending
section. **Raising the threshold without re-measuring per section will block
every meet.**

`RELEVANCE` was removed rather than lowered: it carries no signal here. The
physique-violation probe scored 0.70 relevance — higher than the *honest*
"Discipliner i bevægelse" section at 0.36. With one generic query for every meet
it measures "does this text answer the question", which every section does about
equally. The `query` block stays in the request even so, because
`ApplyGuardrail` rejects the call with a `ValidationException` when a grounding
policy is configured and the query is absent.

What the four denied topics actually catch, probed against the deployed
guardrail: `PersonalCriticism` and `PersonalDetails` fire as topics.
`TalentProjection` and `PhysiqueAndHealth` do **not** — but both probes were
blocked anyway, on grounding, at 0.04 and 0.01: prose of that kind is
ungrounded in a digest of times and points, which is the whole point of the
grounding check. Topic detection is also context-sensitive, so probe a full
section, never a single sentence.

`TalentProjection`'s definition had to be rewritten once. Worded as
"projections about a named athlete's future performance", Bedrock read it
*statistically* and blocked a real report on prose about the field — an
aggregate season trend beside a participation count, no swimmer's future
anywhere in it. Neither sentence fires alone; only the pair. The current
definition names an individual and puts meet statistics out of scope
explicitly, which took the false positives across 12 real sections from 1 to 0
without changing what the violation battery catches.

Config — all three are required in every mode, `--dry-run` included, because the
guardrail's identity is part of the cache key: without it a dry run computes a key
no real run stores under and reports every meet as a miss.

**Via make, there is nothing to export.** `make web-eval` / `web-refresh` /
`eval-models` set all three themselves: the model id is a literal in the
`Makefile` and the guardrail id/version are read live from the deployed
`SwimtrendsEvaluationStack` outputs on every run. That is deliberate — a policy
change publishes a NEW numbered guardrail version, and a *stale export* would
keep pinning the old, weaker one with nothing to warn you. They are `?=`, so an
export still wins when you want one (pinning an older version to compare).

Running the module directly needs them in the environment:

```bash
export EVAL_MODEL_ID=<bedrock model id>
export EVAL_GUARDRAIL_ID=$(aws cloudformation describe-stacks \
  --stack-name SwimtrendsEvaluationStack --profile swimtrends --region eu-west-1 \
  --query "Stacks[0].Outputs[?OutputKey=='GuardrailId'].OutputValue" --output text)
export EVAL_GUARDRAIL_VERSION=$(aws cloudformation describe-stacks \
  --stack-name SwimtrendsEvaluationStack --profile swimtrends --region eu-west-1 \
  --query "Stacks[0].Outputs[?OutputKey=='GuardrailVersion'].OutputValue" --output text)
```

**Re-read both after any redeploy of the stack** if you export them by hand.
`DRAFT` is refused outright.

Two other traps the make targets handle, both of which cost a run to diagnose:
the eval deps (`strands-agents`, `pydantic`) are in `requirements-eval.txt`, not
`requirements.txt`, so a venv built from the latter alone dies at import — the
`eval-preflight` target checks the import up front. And exported
`AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`/`AWS_SESSION_TOKEN` **outrank**
`AWS_PROFILE` in both the boto and DuckDB credential chains, so a shell holding
another account's credentials gets 403 on the curated zone; the `ST_PYTHON`
wrapper in the `Makefile` unsets all three.

The batch operator needs `bedrock:InvokeModel*` on the model /
inference-profile ARN, `bedrock:ApplyGuardrail` on the guardrail ARN (required
both to invoke a model with a guardrail and for the explicit output check), and
`s3:GetObject`/`s3:PutObject` under `swimtrends-meet-data/evaluations/*`.

Useful flags:

- `--dry-run` — report cache hits and misses without calling the model. Needs the
  same three variables as a real run (see above), and deletes nothing: it never
  prunes a stale `evaluation.json`, since no `--delete` sync follows it.
- `--meets DM-L/12486` — one meet (or a comma-separated list).
- `--force` — regenerate and overwrite the cached text. This is the revoke
  switch; the bucket is versioned, so the prior text is retained. It is also the
  only way out of a corrupt cached object: reading one raises, which skips that
  meet on every subsequent run until the object is regenerated or deleted.

The cache key is `sha256(digest + prompt_version + schema_version + model_id +
guardrail_id + guardrail_version + max_tokens)`. Unchanged inputs reuse the
stored text verbatim — bumping `PROMPT_VERSION` or `SCHEMA_VERSION` in
`evaluation/agent.py`, switching models, or publishing a new guardrail version
regenerates every meet on the next run.

Every number in a published evaluation is checked against the digest
(`evaluation/check.py`); a report that fails twice is dropped and the page
renders without the section. A report that passes the number check is then put
through `ApplyGuardrail` **section by section**, and a block is retried exactly
like a fabricated number: the rewrite prompt names the blocked section and the
offence, and only a report that is blocked twice is dropped — nothing is cached
or written then.

The retry exists because the model, not the policy, is what fails here. On the
first real run against a working guardrail, 2 of 3 meets were blocked, each on a
single section carrying a causal claim ("dette skyldes …", "er således en
væsentlig forklarende faktor") that `SYSTEM_PROMPT` rule 6 already forbids. One
drifting section is not worth the whole meet's page section, and the same rule-6
wording now quotes those constructions back at the model.

A meet that fails during `web-eval` (digest error, a bad AI report, a guardrail
block, a transient S3 error) gets no `evaluation.json`: any file an earlier run
left there is deleted, so a skip can never republish superseded text. The
`--delete` sync then removes that meet's section from the live site until a
later run succeeds — the page falls back to rendering without it, same as any
other skip.

What a refused meet looks like — one INFO per blocked section, one WARNING for
the meet:

```
INFO    the guardrail blocked the section 'Bredde': GROUNDING 0.3 < threshold 0.5
WARNING refused DM-L/6980: the guardrail blocked the section 'Bredde' after 1 retry
ERROR   evaluation failed for DM-L/6980   ← + traceback
```

A `refused` **warning** is the policy working — the model wrote a number that
isn't in the digest, or a section the guardrail rejected, twice. Nothing is
wrong with the run; that meet just has no report. An **ERROR with a traceback**
is a real bug or an infrastructure failure and is worth chasing. A refusal
deliberately prints no traceback: six frames per refused meet across 40 meets
reads as a crash and buries the one line that says which section and why.

The score is the useful part of a grounding block: `0.13` is prose the digest
cannot support at all, `0.49` a near miss on the 0.5 threshold. The full
`ApplyGuardrail` assessment is ~700 characters of `invocationMetrics`, coverage
counts and the guardrail ARN — it goes to DEBUG (`log.setLevel(logging.DEBUG)`)
rather than to the batch output, and is where to look if a policy fires that the
one-line summary doesn't name.

The batch also silences two INFO sources that are not batch signals: Strands'
streamed `Tool #17: MeetEvaluation` chatter and the model's own mid-retry text
(`callback_handler=None` in `build_agent`), and botocore's
`Found credentials in shared credentials file` per client (`botocore`, `boto3`,
`strands` pinned to WARNING in `__main__`). A real library error still prints.

### Cost, and the ceiling on it

A full generation of every meet can exhaust the account's **daily** Bedrock
token quota. Observed on the first full-set run: `ThrottlingException: Too many
tokens per day`, after which every remaining meet fails and the run appears to
hang (the retries back off for minutes at a time). Nothing is lost — the meets
already generated are cached, so re-running the next day resumes and pays only
for what is left.

What exhausted it was not the batch's size. A rejected structured-output field
makes Strands re-call the tool, resending the whole conversation **plus every
prior rejection**, so input grows per call and the total grows quadratically:
one misspelled section heading cost **105 tool calls and ~1.4M input tokens on a
single meet**. The day billed ~28M input tokens (**$30.87**) against an expected
~0.2M (~$0.29) — 94% of it input, ~120× over.

Three measures, each addressing a different link in that chain:

| measure | where | what it stops |
| --- | --- | --- |
| the section heading is a schema `Literal` | `Section.heading` | the trigger: the model can read the five legal strings *before* it answers, instead of being told only that its guess was wrong |
| `LIMITS = {"turns": 6, "total_tokens": 40_000}` on every invocation | `evaluate()` | the runaway itself — a hard per-meet ceiling ~10× a healthy meet's spend and ~35× below what the incident cost |
| `input_tokens` / `output_tokens` in the run summary | `run()` | the blindness: `generated=25, skipped=16` read as a healthy run, and the only evidence was the bill two days later |

`limits` is **per invocation, not per agent** — it cannot be set once on the
`Agent`, so an `agent(...)` call that omits it is an uncapped meet. A trip ends
the invocation with a `limit_*` stop reason and no structured output, which is
indistinguishable from an empty answer unless it is named; `evaluate` raises on
it and does **not** retry, since a trip means the meet already spent its whole
allowance. Note what the caps do *not* do: they bound one meet, not the batch, so
41 pathological meets would still cost 41 × 40k. The daily quota is the backstop
there.

If **more meets are skipped than written** — wrong `EVAL_MODEL_ID`, a revoked
guardrail, expired credentials, throttling partway through — `web-eval` exits
non-zero on purpose and `make` stops before the sync. A minority of skips in an
otherwise healthy batch still exits 0, so one stubborn meet does not block every
refresh. Note what a failed run leaves behind: the live site is untouched
(the sync never ran), but the local `web/public/data` is now missing those
meets' sections. Re-running restores them from the cache without calling the
model.

## Site traffic

Web traffic to swimtrends.dk is a **different dataset** from the curated swim
data above — CloudFront access logs in `s3://swimtrends-web-logs/cf/`, read
with:

```bash
cd st-scrape
AWS_PROFILE=swimtrends .venv/bin/python -m ingestion.cli traffic
```

Full walkthrough, recipes and troubleshooting: [`traffic.md`](traffic.md).
