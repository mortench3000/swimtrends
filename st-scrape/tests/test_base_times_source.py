"""gen_base_times.BLOCKS must match the World Aquatics documents in wa-points/.

gen_base_times.py only checks each row against itself (time string vs seconds),
so a value copied into the wrong cell passes it. This found SCM 2022 men's
100 Fly carrying the women's time (54.69 for 47.78).

The markdown is a PDF conversion with known noise: one-decimal times (92.5),
stray spaces (4 :25.87), '4x50' without 'm', an event label on its own line
with the times on the next, and rows without a seconds column. A WA period
can appear in several documents, and one of them may have shifted rows, so a
block row passes if ANY document covering its validity period agrees.
"""
import ast
import glob
import os
import re

HERE = os.path.dirname(__file__)
ROOT = os.path.join(HERE, "..")

STROKE = {"Freestyle": "Free", "Backstroke": "Back", "Breaststroke": "Breast",
          "Butterfly": "Fly", "Medley": "Medley"}
EVENT = re.compile(r"(?:(4)x)?(\d+)m? (Freestyle|Backstroke|Breaststroke|Butterfly|Medley)")
TIME = re.compile(r"^\d+(?::\d\d)?\.\d\d?$")
VALIDITY = re.compile(r"Validity period:\s*(\S+)\s*[–-]\s*(\S+)")


def _blocks():
    # Read BLOCKS as a literal: importing gen_base_times runs it and writes db/.
    src = open(os.path.join(ROOT, "gen_base_times.py"), encoding="utf-8").read()
    node = next(n for n in ast.parse(src).body if isinstance(n, ast.Assign)
                and getattr(n.targets[0], "id", "") == "BLOCKS")
    return ast.literal_eval(node.value)


def _sec(cell):
    mins, _, secs = cell.replace(" ", "").rpartition(":")
    return round(int(mins or 0) * 60 + float(secs), 2)


def _iso(dmy):
    d, m, y = dmy.split(".")
    return f"{y}-{m}-{d}"


def parse_doc(path):
    """{(validity_start, validity_end): {(relay_count, distance, stroke, mixed): [secs…]}}"""
    sections, cur, event, vals, mixed = {}, None, None, [], False
    for line in open(path, encoding="utf-8"):
        v = VALIDITY.search(line)
        if v:
            cur = sections.setdefault((_iso(v.group(1)), _iso(v.group(2))), {})
            event, mixed = None, False
            continue
        if cur is None:
            continue
        if line.strip() == "Mixed":
            mixed = True
            continue
        m = EVENT.search(line)
        if m:
            event = (int(m.group(1) or 1), int(m.group(2)), STROKE[m.group(3)], mixed)
            vals = []
        if event:
            vals += [_sec(c) for c in line.split("|") if TIME.match(c.replace(" ", "").strip())]
            n = 1 if mixed else 2  # mixed relays have one time; others men + women
            if len(vals) >= n:
                # time+seconds pairs -> take the seconds column; times only -> take them
                cur[event] = vals[1::2][:n] if len(vals) >= 2 * n else vals[:n]
                if len(vals) >= 2 * n or "|" in line:
                    event = None
    return sections


def _expected(block):
    want = {}
    for dist, stroke, _mt, ms, _wt, ws in block["individual"]:
        want[(1, dist, stroke, False)] = [ms, ws]
    for rc, dist, stroke, _mt, ms, _wt, ws in block["relay"]:
        want[(rc, dist, stroke, False)] = [ms, ws]
    for rc, dist, stroke, _xt, xs in block["mixed"]:
        want[(rc, dist, stroke, True)] = [xs]
    return want


def test_every_block_row_matches_a_wa_document():
    docs = {}
    for path in sorted(glob.glob(os.path.join(ROOT, "wa-points", "*.md"))):
        for period, rows in parse_doc(path).items():
            docs.setdefault(period, []).append(rows)

    problems = []
    for block in _blocks():
        period = (block["validity_start"], block["validity_end"])
        found = docs.get(period)
        if not found:
            problems.append(f"{block['wa_label']}: no wa-points/*.md section for {period}")
            continue
        for key, want in _expected(block).items():
            if not any(doc.get(key) == want for doc in found):
                problems.append(f"{block['wa_label']} {key}: generator {want}, "
                                f"docs {[doc.get(key) for doc in found]}")
    assert not problems, "\n".join(problems)
