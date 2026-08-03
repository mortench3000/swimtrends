"""Every number in a published evaluation must appear in its digest.

This is the deterministic half of "don't make things up" — cheap, total, and
independent of the model and the guardrail. The prompt forbids the model from
computing figures; percentages it may quote are precomputed in digest["derived"],
so no arithmetic needs licensing here.
"""
import re

# A time (2:11.40), or a plain integer/decimal. Longest alternative first so a
# time is captured whole rather than as its pieces.
_TOKEN = re.compile(r"\d+:\d{1,2}[.,]\d{1,2}|\d+(?:[.,]\d+)?")


def _norm(token: str) -> str:
    """Danish decimal comma -> dot. Nothing else: a token's digits are compared
    as written, so leading zeros are significant."""
    return token.replace(",", ".")


def _time_variants(value: str) -> set[str]:
    """A digest time licenses its own form and the way prose usually writes it:
    every time also licenses its bare seconds part, so '0:52.00' licenses
    '52.00' and '2:11.40' licenses '11.40'."""
    out = {_norm(value)}
    m = re.fullmatch(r"(\d+):(\d{1,2}[.,]\d{1,2})", value or "")
    if m:
        out.add(_norm(m.group(2)))
    return out


def _walk(obj, out: set[str]) -> None:
    if isinstance(obj, dict):
        for v in obj.values():
            _walk(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _walk(v, out)
    elif isinstance(obj, bool) or obj is None:
        return
    elif isinstance(obj, (int, float)):
        normalized = _norm(str(obj))
        out.add(normalized)
        # An int is also licensed with its sign stripped: derived deltas are
        # negative in the digest but prose says "3% under".
        out.add(_norm(str(abs(obj))))
        # For 4+ digit integers, also allow Danish thousands-grouped form
        # (e.g., 1234 → also allow 1.234)
        if isinstance(obj, int) and abs(obj) >= 1000:
            # Format with thousands separator: 1234 → "1.234"
            grouped = f"{abs(obj):,}".replace(",", ".")
            out.add(grouped)
    elif isinstance(obj, str):
        if re.fullmatch(r"\d+:\d{1,2}[.,]\d{1,2}", obj):
            # A time string licenses its variants
            out |= _time_variants(obj)
        elif re.fullmatch(r"\d{1,2}[.,]\d{1,2}", obj):
            # A bare M.SS swim time (no minute component — sub-minute races,
            # e.g. curated 50/100m times like "24.66") licenses itself.
            out.add(_norm(obj))
        else:
            # Only extract the distance from event labels (e.g., "F 200m Fly (LCM)" → 200).
            # Ignore dates, swimmer names, club names, and other free text.
            m = re.search(r"(\d+)m\b", obj)
            if m:
                out.add(m.group(1))


def _club_names(digest: dict) -> set[str]:
    """Every club name the digest carries, from all three blocks that name one.

    Kept in one place because two consumers need the same set: the digit
    licence in allowed_numbers, and the masking in check_attribution.
    """
    out: set[str] = set()
    for key in ("top_swims", "clubs", "multi_title_swimmers"):
        for row in digest.get(key) or []:
            club = row.get("club") if isinstance(row, dict) else None
            if isinstance(club, str):
                out.add(club)
    return out


def _named_swimmers(digest: dict) -> set[str]:
    """Every swimmer the digest names, i.e. every name the prose may use."""
    out: set[str] = set()
    for key in ("top_swims", "multi_title_swimmers"):
        for row in digest.get(key) or []:
            name = row.get("name") if isinstance(row, dict) else None
            if isinstance(name, str):
                out.add(name)
    return out


def allowed_numbers(digest: dict) -> set[str]:
    out: set[str] = set()
    _walk(digest, out)
    # The size of the comparison window itself: how many prior seasons are
    # included in the digest. If season_history has 6 entries, then "5" (the
    # number of prior seasons) and "6" (the window size) are both licensable.
    window_size = len(digest.get("season_history", []))
    out.add(str(window_size))
    out.add(str(max(window_size - 1, 0)))
    # meet.name is the meet's own title as shown on the page (e.g. "DM
    # Kortbane 2016") — a model naturally quotes it, so its digits are
    # licensed. meet.date is deliberately NOT walked this way: that string
    # licensing bare date components (e.g. "10" from "2026-04-10") as
    # fabricated medal/count numbers was the original leak this guard fixed.
    name = digest.get("meet", {}).get("name")
    if isinstance(name, str):
        out.update(re.findall(r"\d+", name))
    # Club names carry digits — "Svømmeklubben MK31", "A6 JGI-Swim". The prompt
    # licenses naming a club, so those digits arrive in the prose by design;
    # flagging them as fabricated spends the meet's single rewrite on a false
    # positive (this is what left DM-K/7088 unpublished). Only club names, and
    # only the digit runs as written — the rest of the digest's free text stays
    # unlicensed, which is the leak _walk deliberately avoids.
    for club in _club_names(digest):
        out.update(re.findall(r"\d+", club))
    return out


def numbers_in_text(text: str) -> set[str]:
    out: set[str] = set()
    for token in _TOKEN.findall(text or ""):
        normalized = _norm(token)
        out.add(normalized)
        # Handle Danish thousands separators: if a token looks like 1.234
        # (1-3 digits, then one or more groups of .DDD), add the ungrouped form too.
        if re.fullmatch(r"\d{1,3}(\.\d{3})+", token):
            ungrouped = token.replace(".", "")
            out.add(ungrouped)
    return out


def check_numbers(text: str, digest: dict) -> set[str]:
    """The numeric tokens in `text` that the digest does not license."""
    return numbers_in_text(text) - allowed_numbers(digest)


# --- gendered event claims ---------------------------------------------------
# Men's and women's races share a name, so digest.top_swims[].event carries a
# marker ("F 50m Ryg (LCM)") and SYSTEM_PROMPT rule 9 tells the model to carry
# it into the prose. Nothing enforced that until now, and the model can state
# the opposite of what the digest says: DM-L/9775 published "Pauline Mahieu ...
# vandt herrernes 50m Ryg" against a digest row reading F.
#
# Neither existing gate can see it. check_numbers reads numeric tokens, and
# every figure in that sentence was right. The guardrail scores a whole section,
# where one inverted word is lost in a paragraph of correct times and points —
# measured on that exact section: 0.88 grounding as published, 0.92 with only
# the gender corrected. A 0.04 cost for a factual claim about a named athlete is
# not a gate, so this check is deterministic instead.

# The Danish forms the reports actually use, plus the digest's own raw markers
# (rule 9 permits either). Longest first so "herrernes" is not matched as
# "herrer".
_GENDER_WORDS = {
    "herrernes": "M", "herrerne": "M", "herrer": "M",
    "mændenes": "M", "mændene": "M",
    "damernes": "F", "damerne": "F", "damer": "F",
    "kvindernes": "F", "kvinderne": "F", "kvinder": "F",
    "m": "M", "f": "F",
}
_STROKES = "Fri|Ryg|Bryst|Fly|IM|HM"
# A gender token, then a distance+stroke close behind it. `[^.]` keeps a match
# inside one sentence: "Blandt herrerne var niveauet højt. Hun vandt 50m Ryg"
# must not read as a claim about a men's race. (A decimal point ends the window
# early, which only ever costs a match — it never invents one.)
_CLAIM = re.compile(
    rf"\b({'|'.join(_GENDER_WORDS)})\b[^.]{{0,40}}?\b([\dx]+)m\s+({_STROKES})\b",
    re.IGNORECASE)
# The same shape on the digest side: "F 50m Ryg (LCM)".
_EVENT = re.compile(rf"^([MFX])\s+([\dx]+)m\s+({_STROKES})\b", re.IGNORECASE)


# --- misattributed figures ---------------------------------------------------
# The other half of the same problem: the figure is real but bound to the wrong
# athlete. A regenerated DMJ-L/11712 credited Lucas Linderoth with "M 1500m Fri
# (772 point)" — Mathias Hald's result — and called it his fourth win when he
# had three. check_numbers passed (772 is in the digest) and the guardrail
# passed, because nothing either of them looks at was false in isolation.
#
# Only the name->points binding is judged, and only where the digest settles it.
# ponytail: points only, not times. The same map keyed on time strings would
# extend it, and the observed errors were all points.

# "848 point" / "848 points" — a figure in the attributive position reports use.
_POINTS = re.compile(r"\b(\d+)\s+points?\b", re.IGNORECASE)
# A figure can also appear comparatively, and then it is nobody's result:
# "pointgennemsnit på over 850 point" (DM-L/6516) and "præsterede på 720-750
# point" (DMJ-L/8609) both bound a threshold to the last swimmer named, which
# would have rejected two correct reports. A Danish comparison word just before
# the number, or a range dash joining it to another number, means the figure is
# describing a band rather than crediting anyone.
_COMPARATIVE = re.compile(
    r"(?:\b(?:over|under|omkring|cirka|ca\.?|mindst|højst|mellem|op\s+til|"
    r"ned\s+til)\s+|\d\s*[-–—]\s*)$", re.IGNORECASE)
# How far back a name may sit and still own a figure. One sentence of this
# prose ("Lucas Linderoth fra Sigma Swim Allerød satte resultat i tre
# discipliner: M 50m Fri med 753 point, ...") runs to ~150 characters, so the
# window has to clear that; beyond it the binding is guesswork and the check
# stays quiet rather than reject correct prose.
_BIND_WINDOW = 250
# Two or more capitalised words in a row — a person's name in Danish prose,
# where only the first word of a sentence is otherwise capitalised. Used to
# detect somebody standing between a known swimmer and a figure. Club names
# match this too ("Swim Team Odense"), which is why the digest's own club
# strings are removed from the text before this runs: a club sits between the
# swimmer and the figure in almost every sentence these reports write.
_PERSON = re.compile(r"\b[A-ZÆØÅ][\wÆØÅæøå.'-]*(?:\s+[A-ZÆØÅ][\wÆØÅæøå.'-]*)+")


def _aggregate_values(digest: dict) -> set[str]:
    """Digest numbers that are *not* one swimmer's result.

    A median or an entrant count that happens to equal somebody's points makes
    the provenance of that figure ambiguous, so it is excluded from the check.
    top_points is deliberately kept: it is by definition the best swim's score,
    the same number owned by the same swimmer.
    """
    out: set[str] = set()
    facts = {k: v for k, v in (digest.get("facts") or {}).items()
             if k != "top_points"}
    for block in (facts, digest.get("derived") or {}):
        _walk(block, out)
    for block in (digest.get("season_history") or [], digest.get("by_stroke") or [],
                  digest.get("clubs") or []):
        _walk(block, out)
    return out


def points_owners(digest: dict) -> dict[str, set[str]]:
    """points value -> the lowercased swimmer names the digest credits with it."""
    ambiguous = _aggregate_values(digest)
    out: dict[str, set[str]] = {}
    for swim in digest.get("top_swims", []):
        if not isinstance(swim, dict):
            continue
        points, name = swim.get("points"), swim.get("name")
        if points is None or not isinstance(name, str):
            continue
        key = str(points)
        if key in ambiguous:
            continue
        out.setdefault(key, set()).add(name.lower())
    for row in digest.get("multi_title_swimmers") or []:
        if not isinstance(row, dict):
            continue
        name = row.get("name")
        if not isinstance(name, str):
            continue
        for win in row.get("wins") or []:
            points = win.get("points") if isinstance(win, dict) else None
            if points is None:
                continue
            key = str(points)
            if key in ambiguous:
                continue
            out.setdefault(key, set()).add(name.lower())
    return out


def check_attribution(text: str, digest: dict) -> set[str]:
    """Points figures in `text` credited to a swimmer the digest says is not
    their owner, as "Name: points".

    The nearest preceding digest name within `_BIND_WINDOW` is taken as the
    claimed owner. No name in range means no claim to judge — reports quote
    aggregate figures with no swimmer attached, and those are not this check's
    business. A figure two swimmers share licenses either of them.
    """
    text = text or ""
    owners = points_owners(digest)
    if not owners:
        return set()
    # Where each digest swimmer is named, case-insensitively: the reports
    # sometimes shout a name ("PAULINE MAHIEU") exactly as the source does.
    mentions: list[tuple[int, str]] = []
    for name in _named_swimmers(digest):
        for m in re.finditer(re.escape(name), text, re.IGNORECASE):
            mentions.append((m.start(), name.lower()))
    mentions.sort()
    # Blank the digest's club strings (same length, so every offset above stays
    # valid) before looking for an intervening person: "Thea Blomsterberg fra
    # Swim Team Odense vandt ... 834 point" puts a capitalised club between the
    # swimmer and her figure in almost every sentence these reports write.
    masked = text
    for club in _club_names(digest):
        masked = re.sub(re.escape(club), " " * len(club), masked, flags=re.IGNORECASE)

    offenders = set()
    for m in _POINTS.finditer(text):
        value = m.group(1)
        if value not in owners:
            continue
        if _COMPARATIVE.search(text, max(0, m.start() - 12), m.start()):
            continue
        prior = [(pos, n) for pos, n in mentions if pos < m.start()]
        if not prior:
            continue
        pos, claimed = prior[-1]
        if m.start() - pos > _BIND_WINDOW:
            continue
        # A person named between that swimmer and the figure owns the figure,
        # not the swimmer upstream of them — and if the digest doesn't carry
        # them, this check cannot say whose result it is. Staying silent beats
        # blaming the wrong person: on DM-K/10340 the naive binding reported
        # "Karoline Barrett: 845" for a sentence that credits Frederik
        # Lindholm. (Naming a swimmer outside the digest is its own violation;
        # it is not this function's to report.)
        if _PERSON.search(masked, pos + len(claimed), m.start()):
            continue
        if claimed not in owners[value]:
            offenders.add(f"{claimed.title()}: {value}")
    return offenders


def genders_in_digest(digest: dict) -> dict[tuple[str, str], set[str]]:
    """(distance, stroke) -> the genders the digest actually holds.

    Both name-carrying blocks contribute: a swimmer's title is as much a
    gendered claim as a top swim, and an event absent here is simply unjudged.
    """
    events = [swim.get("event") for swim in digest.get("top_swims", [])
              if isinstance(swim, dict)]
    for row in digest.get("multi_title_swimmers") or []:
        if not isinstance(row, dict):
            continue
        events += [win.get("event") for win in row.get("wins") or []
                   if isinstance(win, dict)]
    out: dict[tuple[str, str], set[str]] = {}
    for event in events:
        m = _EVENT.match(str(event or ""))
        if m:
            out.setdefault((m.group(2).lower(), m.group(3).lower()),
                           set()).add(m.group(1).upper())
    return out


def check_genders(text: str, digest: dict) -> set[str]:
    """Gendered event claims in `text` that contradict the digest.

    Only claims about an event the digest actually carries are judged. top_swims
    is a top-N list, so most of a meet's races are absent from it, and treating
    "absent" as "wrong" would reject correct prose. An event held for both
    genders licenses either — that is not a contradiction, just a shared name.
    """
    held = genders_in_digest(digest)
    offenders = set()
    for word, distance, stroke in _CLAIM.findall(text or ""):
        claimed = _GENDER_WORDS[word.lower()]
        offered = held.get((distance.lower(), stroke.lower()))
        if offered and claimed not in offered:
            offenders.add(f"{word} {distance}m {stroke}")
    return offenders


# --- foreign words and digest jargon -----------------------------------------
# The fourth failure class, and the one no other gate here can see: the prose is
# not Danish. check_numbers reads digits, check_genders and check_attribution
# read bindings, and Bedrock's grounding score judges whether a sentence is
# *supported* — a malformed verb inside a factually correct sentence passes all
# of them, so a language error used to survive every retry by construction.
#
# Haiku 4.5 produced ~60 of these across 40 published reports (Bokmål drift,
# English intrusion, invented compounds), which is why the batch runs on Sonnet
# 4.6 now — see docs/analytics.md. This list is the backstop for what a good
# model still slips through, and it is deliberately a list of *observed* forms
# rather than a dictionary: Danish compounding is productive, so correct words
# like "femårsgennemsnittet" appear in no word list and a dictionary gate would
# reject good prose all day. The cost of that choice is that a brand-new typo
# passes; the fix is one more entry here, and the offender is named in the
# refusal message.
_NOT_DANISH = frozenset({
    # Norwegian/Swedish forms, all seen in published reports.
    "hadde", "blant", "antall", "basert", "deltakere", "deltakertal",
    "deltakermedian", "deltakelsen", "etterfulgt", "gjennomsnitt", "grenar",
    # "historikk" only — Danish has "historik", so "historikken" is the correct
    # definite form and flagging it would have re-rolled 20 good reports.
    "greningrupper", "historikk", "høyeste", "høyest",
    "medalievinnere", "medaljespeilet", "medianpoeng", "oppgikk", "oppnådde",
    "plass", "plasseringer", "poengsum", "prestation", "representert",
    "sammensetning", "seire", "sesongers", "vant", "økning",
    # Digest field names and English technical tokens — rule 8 already forbids
    # these, and they still arrive verbatim ("digest.derived angiver 0 procent",
    # "negative deltas", "over 46 events").
    "digest", "derived", "deltas", "deltaer", "events", "stroke", "strokes",
    "strokearter", "stroketyper", "slagarter", "podiums", "performance",
    "longdistancer", "longbanenivået", "mediumdistance", "mediemdistance",
    "langtidsstroker",
    # Invented words and transpositions. Each one was published.
    "bredtevældet", "brystsvømmingen", "conquisterede", "flageslagsdiscipliner",
    "frisvømming", "frisvømmingen", "førtede", "guldmedajer", "herernes",
    "herremændenes", "højteste", "langtbane", "mediaanresultat",
    "deltagtallet", "mødetets", "pokaljepladser", "sichrede", "sprintintersvig",
    "stemmmer", "topede", "topsværgmelser", "umplaceringer", "velrepsentierede",
    "vindersømmninger",
})
_WORD = re.compile(r"[A-Za-zÆØÅæøå]+")
# One word this model mangles reliably and *differently* every time —
# podieplacerigner, podieplacerringer, podieplaceriger, podieplaceriner in four
# reports. Enumerating misspellings loses that race; every correct form
# continues "podieplacer" with "ing", so the negative lookahead catches the
# whole family, including the ones not written yet.
_MANGLED = re.compile(r"\bpodieplacer(?!ing)[a-zæøå]*", re.IGNORECASE)


def check_language(text: str, digest: dict) -> set[str]:
    """Words in `text` that are not Danish, or are digest jargon.

    Words the digest itself uses as a name are never flagged: the list is blind
    to proper nouns, and a swimmer called "Vant" or a club called "Plass Swim"
    would otherwise be rewritten forever.
    """
    names = " ".join(_named_swimmers(digest) | _club_names(digest)).lower()
    proper = set(_WORD.findall(names))
    found = {w.lower() for w in _WORD.findall(text or "")} & _NOT_DANISH
    found |= {m.group(0).lower() for m in _MANGLED.finditer(text or "")}
    return found - proper
