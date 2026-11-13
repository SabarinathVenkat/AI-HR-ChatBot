"""Bold the key words in a bullet, the way some templates do.

Only when the template itself does it (see `has_emphasis` in template.py). The words are the resume's own skill names
found in the text, so this is plain formatting: the text is never changed and nothing is added. Neighbouring terms
("C#, .NET Core and ASP.NET Web API") become one bold phrase, like a human editor would do.
"""
import re

from app.rmg.resume.model import Resume

MIN_TERM_CHARS = 2  # "R" or "C" alone would match inside ordinary text
MAX_BOLD_SHARE = 0.7  # a bullet that would be nearly all bold is left plain: that is not emphasis
_JOINER = re.compile(r"^\s*(?:,|/|&|\band\b|\bor\b|,\s*and\b|,\s*or\b)\s*$", re.IGNORECASE)


def terms_of(resume: Resume) -> list[str]:
    """The resume's skills, and what is inside any brackets ("AWS (S3, EC2)" gives AWS, S3 and EC2)."""
    found: dict[str, None] = {}
    for group in resume.skill_groups:
        for item in group.items:
            text = " ".join(item.text.split())
            head, _, rest = text.partition("(")
            candidates = [text, head.strip(), *(part.strip(" )") for part in rest.split(","))]
            for candidate in candidates:
                if len(candidate) >= MIN_TERM_CHARS:
                    found.setdefault(candidate, None)
    return list(found)


def _pattern(term: str) -> re.Pattern:
    words = r"\s+".join(re.escape(w) for w in term.split())
    return re.compile(r"(?<![A-Za-z0-9])" + words + r"(?![A-Za-z0-9+#])", re.IGNORECASE)


def emphasise(text: str, terms: list[str]) -> list[tuple[str, bool]]:
    """The text as (piece, bold) segments. With no term found, or too many, it is one plain segment."""
    taken = [False] * len(text)
    spans: list[tuple[int, int]] = []
    for term in sorted(set(terms), key=len, reverse=True):  # longest first, so ".NET Core" wins over "NET"
        for match in _pattern(term).finditer(text):
            if not any(taken[match.start():match.end()]):
                spans.append((match.start(), match.end()))
                for i in range(match.start(), match.end()):
                    taken[i] = True
    spans.sort()
    merged: list[list[int]] = []
    for start, end in spans:
        if merged and _JOINER.match(text[merged[-1][1]:start]):
            merged[-1][1] = end
        else:
            merged.append([start, end])
    if not merged or sum(end - start for start, end in merged) > MAX_BOLD_SHARE * len(text):
        return [(text, False)]
    segments, cursor = [], 0
    for start, end in merged:
        if start > cursor:
            segments.append((text[cursor:start], False))
        segments.append((text[start:end], True))
        cursor = end
    if cursor < len(text):
        segments.append((text[cursor:], False))
    return segments
