"""Check a tailored resume against the original: nothing may be claimed that the original does not support.

This is the guardrail. A model can be told "never invent a skill", but being told is not the same as being stopped. This script
reads both texts and reports, line by line, anything in the tailored resume that the original does not support:

  missing_skill  a skill the JD wants, that the original does not show, appears in the tailored text
  new_number     a number (a count, a year, a percentage) that is not in the original
  new_term       a technology-looking word (CamelCase, with digits or + or #, or a capitalised word in mid-sentence)
                 that appears nowhere in the original

A skill the candidate has confirmed is theirs to claim, so pass it with --confirmed and it is not reported.
A skill added for the match without evidence (Bridge and Summit only, after warning the person) goes in --added: it is accepted, and a
WARNING line for it is printed to paste into the note.
A skill you inferred from evidence in the resume (Spring from Spring Boot) goes in --inferred: it is accepted only if the resume really
contains such evidence (see related.py); otherwise it is reported.
When you check a finished Word file, pass the template with --template: its own words (headings such as KEY HIGHLIGHTS) are
the template's, not claims. The template never excuses a skill the resume lacks: missing_skill is still reported.

Usage:
  python check_claims.py --original resume.txt --tailored tailored.txt --required "Java, Kafka" --nice "AWS" [--confirmed "Kafka"] [--inferred "Spring"] [--added "Terraform"] [--template assets/template.docx]
Files may be .txt, .md or .docx. Exit code 0 means clean; 1 means something was reported; 2 means a file could not be read.
Needs only the standard library, plus python-docx for .docx files.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # related.py sits beside this file

_NUMBER = re.compile(r"\d+(?:[.,]\d+)*%?")
_TOKEN = re.compile(r"[A-Za-z](?:[A-Za-z0-9+#.]*[A-Za-z0-9+#])?")
_SENTENCE_END = re.compile(r"[.!?]\s+$")


def read_text(path: str) -> str:
    """The text of a .txt, .md or .docx file (a docx includes the text in its tables)."""
    p = Path(path)
    if p.suffix.lower() == ".docx":
        from docx import Document  # python-docx

        doc = Document(str(p))
        lines = [para.text for para in doc.paragraphs]
        for table in doc.tables:
            for row in table.rows:
                seen = set()
                for cell in row.cells:
                    if id(cell._tc) in seen:  # a merged cell appears once per column it spans
                        continue
                    seen.add(id(cell._tc))
                    lines += [para.text for para in cell.paragraphs]
        return "\n".join(lines)
    return p.read_text(encoding="utf-8", errors="replace")


def split_skills(value: str | None) -> list[str]:
    return [s.strip() for s in re.split(r"[,;\n]", value or "") if s.strip()]


def mentions(text: str, skill: str) -> bool:
    """True if `skill` is in `text` as a whole word, ignoring case ("Java" is not in "JavaScript", "C" is not in "C++")."""
    words = skill.split()
    if not words:
        return False
    pattern = r"(?<![A-Za-z0-9])" + r"\s+".join(re.escape(w) for w in words) + r"(?![A-Za-z0-9+#])"
    return re.search(pattern, text, re.IGNORECASE) is not None


def _words(text: str) -> list[tuple[str, int]]:
    """Each word with a position. The first word of a sentence gets position 0, so a capital letter that only starts a sentence
    ("Redesigned the batch jobs.") is not taken for the name of a technology."""
    out = []
    for n, m in enumerate(_TOKEN.finditer(text)):
        out.append((m.group(0), 0 if _SENTENCE_END.search(text[:m.start()]) else n))
    return out


def _looks_technical(token: str, position: int) -> bool:
    return (any(c.isupper() for c in token[1:]) or any(c.isdigit() or c in "+#" for c in token)
            or (token[0].isupper() and position > 0))


def check(original: str, tailored: str, required: list[str], nice: list[str], confirmed: list[str] = (),
          allow: list[str] = (), template: str = "", inferred: list[str] = (), added: list[str] = ()) -> list[dict]:
    """Everything in `tailored` that `original` does not support, as a list of {line, kind, detail, text}.
    `template` is the text of the company template: its words are not claims, so they are not reported as new terms."""
    vocabulary = {t.casefold() for t in _TOKEN.findall(original)} | {t.casefold() for t in _TOKEN.findall(template)}
    numbers = set(_NUMBER.findall(original))
    from related import evidence_for

    problems: list[dict] = []
    supported = []
    for skill in inferred:
        if evidence_for(skill, original):
            supported.append(skill)
        else:
            problems.append({"line": 0, "kind": "inferred_without_evidence", "detail": skill,
                             "text": "the resume has nothing that shows this skill: only the candidate can claim it (use --confirmed)"})
    accepted = {a.casefold() for a in [*confirmed, *allow, *supported, *added]}
    accepted |= {part.casefold() for a in [*confirmed, *supported, *added] for part in _TOKEN.findall(a)}  # the parts of "CI/CD" are not new terms
    not_shown = [s for s in [*required, *nice] if not mentions(original, s) and s.casefold() not in accepted]
    for number, line in enumerate(tailored.splitlines(), 1):
        if not line.strip():
            continue
        flagged: set[str] = set()
        for skill in not_shown:
            if mentions(line, skill):
                problems.append({"line": number, "kind": "missing_skill", "detail": skill, "text": line.strip()})
                flagged.update(w.casefold() for w in skill.split())
        for n in dict.fromkeys(_NUMBER.findall(line)):
            if n not in numbers and n.casefold() not in accepted:
                problems.append({"line": number, "kind": "new_number", "detail": n, "text": line.strip()})
        for token, position in _words(line):
            key = token.casefold()
            if key not in vocabulary and key not in flagged and key not in accepted and _looks_technical(token, position):
                problems.append({"line": number, "kind": "new_term", "detail": token, "text": line.strip()})
                flagged.add(key)
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--original", required=True, help="the candidate's resume (.txt, .md or .docx)")
    parser.add_argument("--tailored", required=True, help="the tailored resume text (.txt, .md or .docx)")
    parser.add_argument("--required", default="", help="must-have JD skills, comma separated")
    parser.add_argument("--nice", default="", help="nice-to-have JD skills, comma separated")
    parser.add_argument("--confirmed", default="", help="skills the candidate confirmed they have, comma separated")
    parser.add_argument("--inferred", default="", help="skills inferred from evidence in the resume (checked against related.py)")
    parser.add_argument("--added", default="", help="skills added for the match without evidence (Bridge and Summit only), comma separated")
    parser.add_argument("--template", help="the company template (.docx): its own words are not claims")
    parser.add_argument("--allow", default="", help="other words or numbers you have checked and accept, comma separated")
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    args = parser.parse_args(argv)
    try:
        original, tailored = read_text(args.original), read_text(args.tailored)
        template = read_text(args.template) if args.template else ""
    except (OSError, ImportError) as error:
        print(f"Could not read a file: {error}", file=sys.stderr)
        return 2
    problems = check(original, tailored, split_skills(args.required), split_skills(args.nice),
                     split_skills(args.confirmed), split_skills(args.allow), template, split_skills(args.inferred),
                     split_skills(args.added))
    if args.json:
        print(json.dumps({"ok": not problems, "problems": problems}, indent=2))
    elif not problems:
        print("CHECK PASSED: nothing in the tailored resume goes beyond the original.")
    else:
        print(f"CHECK FAILED: {len(problems)} problem(s). Put the original wording back for these lines, then run it again.\n")
        for p in problems:
            print(f"  line {p['line']}: {p['kind']} '{p['detail']}'\n      {p['text']}")
    for skill in split_skills(args.added):
        where = [str(n) for n, line in enumerate(tailored.splitlines(), 1) if mentions(line, skill)]
        print(f"WARNING added for the match, not in the original resume: {skill} (tailored line {', '.join(where) or 'not found'}). "
              "The candidate must approve it before the resume goes to a client.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
