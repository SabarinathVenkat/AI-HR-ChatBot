"""Where a resume stands against the three match levels, and what may honestly be done to reach the next one.

The levels (each has its own name):
  mirror  as is: the resume's own skills only, no target
  bridge  at least 50 percent of the must-have skills shown
  summit  at least 80 percent of the must-have skills shown

For the level asked, this prints the percentage now, how many more must-have skills are needed, and for every gap:
  - EVIDENCE: the resume already contains something that really shows the skill (Spring Boot shows Spring), and in which lines.
              You may write the skill into the project where that evidence is, and must list it as "inferred" in the note.
  - NO EVIDENCE: nothing in the resume shows it. Ask the candidate first; if there is no answer, Bridge and Summit may add it with a
              warning and a note (see reference/match-levels.md). Mirror never adds it.
This script only reads and reports: it never changes a resume. It says how many skills the level still needs after the evidence.

Usage:
  python match_level.py --resume resume.docx --required "A, B, C" --nice "D, E" --level summit [--confirmed "X"] [--json]
Needs only the standard library, plus python-docx for .docx files.
"""
import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_claims import mentions, read_text, split_skills  # noqa: E402
from related import evidence_for  # noqa: E402

LEVELS = {"mirror": None, "bridge": 50, "summit": 80}


def plan(text: str, required: list[str], nice: list[str], level: str, confirmed: list[str] = ()) -> dict:
    target = LEVELS[level]
    confirmed_keys = {c.casefold() for c in confirmed}

    def shown(skill: str) -> bool:
        return mentions(text, skill) or skill.casefold() in confirmed_keys

    shown_required = [s for s in required if shown(s)]
    percent = round(100 * len(shown_required) / len(required)) if required else None
    gaps = [s for s in [*required, *nice] if not shown(s)]
    with_evidence = {s: evidence_for(s, text) for s in gaps}
    mappable = [s for s in required if s in gaps and with_evidence[s]]
    ask = [s for s in gaps if not with_evidence[s]]
    needed = 0
    if target is not None and required:
        needed = max(0, math.ceil(target * len(required) / 100) - len(shown_required))
    reachable = len(shown_required) + len(mappable)
    reachable_percent = round(100 * reachable / len(required)) if required else None
    return {
        "level": level, "target_percent": target, "required_total": len(required), "required_percent": percent,
        "needed_more": needed, "evidence": {s: with_evidence[s] for s in gaps if with_evidence[s]}, "no_evidence": ask,
        "percent_with_evidence": reachable_percent,
        "reached_with_evidence": target is None or (reachable_percent is not None and reachable_percent >= target),
        "needed_without_evidence": 0 if target is None or not required else max(0, needed - len(mappable)),
        "add_if_no_answer": [s for s in required if s in ask][: 0 if target is None else max(0, needed - len(mappable))],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--resume", required=True)
    parser.add_argument("--required", default="")
    parser.add_argument("--nice", default="")
    parser.add_argument("--level", choices=sorted(LEVELS), default="mirror")
    parser.add_argument("--confirmed", default="", help="skills the candidate confirmed they have, comma separated")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        text = read_text(args.resume)
    except (OSError, ImportError) as error:
        print(f"Could not read the resume: {error}", file=sys.stderr)
        return 2
    result = plan(text, split_skills(args.required), split_skills(args.nice), args.level, split_skills(args.confirmed))
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    name = args.level.upper()
    target = f"target {result['target_percent']} percent" if result["target_percent"] else "no target"
    print(f"Level {name} ({target}). Must-haves shown now: {result['required_percent']} percent.")
    if result["target_percent"]:
        print(f"  Needed to reach it: {result['needed_more']} more must-have skill(s).")
    for skill, found in result["evidence"].items():
        print(f"  EVIDENCE {skill}: the resume shows {', '.join(found)}. May be written in as 'inferred'.")
    for skill in result["no_evidence"]:
        print(f"  NO EVIDENCE {skill}: nothing in the resume shows it. Ask the candidate first.")
    if result["target_percent"]:
        if result["reached_with_evidence"]:
            print(f"With the evidence-backed skills the level is reachable ({result['percent_with_evidence']} percent).")
        else:
            print(f"With evidence alone the best is {result['percent_with_evidence']} percent. The level still needs "
                  f"{result['needed_without_evidence']} must-have(s) with no evidence: ask the candidate; if no answer, Bridge and Summit may add "
                  f"{', '.join(result['add_if_no_answer'])} with the warning.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
