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
    # licenses naming a swimmer's club, so those digits arrive in the prose by
    # design; flagging them as fabricated spends the meet's single rewrite on a
    # false positive (this is what left DM-K/7088 unpublished). Only top_swims
    # clubs, and only the digit runs as written — the rest of the digest's free
    # text stays unlicensed, which is the leak _walk deliberately avoids.
    for swim in digest.get("top_swims", []):
        club = swim.get("club") if isinstance(swim, dict) else None
        if isinstance(club, str):
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


def genders_in_digest(digest: dict) -> dict[tuple[str, str], set[str]]:
    """(distance, stroke) -> the genders digest.top_swims actually holds."""
    out: dict[tuple[str, str], set[str]] = {}
    for swim in digest.get("top_swims", []):
        if not isinstance(swim, dict):
            continue
        m = _EVENT.match(str(swim.get("event") or ""))
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
