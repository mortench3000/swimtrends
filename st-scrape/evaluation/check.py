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
        out.add(_norm(str(obj)))
        # An int is also licensed with its sign stripped: derived deltas are
        # negative in the digest but prose says "3% under".
        out.add(_norm(str(abs(obj))))
    elif isinstance(obj, str):
        if re.fullmatch(r"\d+:\d{1,2}[.,]\d{1,2}", obj):
            out |= _time_variants(obj)
        else:
            # Free text (names, event labels, dates) contributes its numbers:
            # an event label like "F 200m Fly (LCM)" licenses 200.
            for tok in _TOKEN.findall(obj):
                out.add(_norm(tok))


def allowed_numbers(digest: dict) -> set[str]:
    out: set[str] = set()
    _walk(digest, out)
    # The size of the comparison window itself ("de sidste 5 sæsoner").
    out.add("5")
    out.add(str(len(digest.get("season_history", []))))
    out.add(str(max(len(digest.get("season_history", [])) - 1, 0)))
    return out


def numbers_in_text(text: str) -> set[str]:
    return {_norm(t) for t in _TOKEN.findall(text or "")}


def check_numbers(text: str, digest: dict) -> set[str]:
    """The numeric tokens in `text` that the digest does not license."""
    return numbers_in_text(text) - allowed_numbers(digest)
