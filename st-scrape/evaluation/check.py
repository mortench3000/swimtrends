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
    """Danish decimal comma -> dot; drop a thousands separator-free integer's
    leading zeros only when it would still be non-empty."""
    return token.replace(",", ".")


def _time_variants(value: str) -> set[str]:
    """A digest time licenses its own form and the way prose usually writes it:
    '0:52.00' also licenses '52.00'."""
    out = {_norm(value)}
    m = re.fullmatch(r"(\d+):(\d{1,2}[.,]\d{1,2})", value or "")
    if m:
        out.add(_norm(m.group(2)))
        if m.group(1) == "0":
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
